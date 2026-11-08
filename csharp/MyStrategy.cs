using System.Collections.Generic;
using System.Linq;
using Aicup2020.Model;

// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

namespace Aicup2020
{
    public class MyStrategy
    {
        static readonly EntityType[] BasesWanted = { EntityType.BuilderBase, EntityType.RangedBase };
        const int FirstBuilders = 5;   // the builder base spends first until it has this many; then the fighting bases do
        const int MaxBuilders = 12;
        const int ArmySize = 8;        // fighting units wait at home until there are this many of them
        const int RepairRange = 6;     // a builder this close to a damaged or unfinished building goes to repair it

        public Action GetAction(PlayerView playerView, DebugInterface debugInterface)
        {
            int me = playerView.MyId;
            int size = playerView.MapSize;
            var props = playerView.EntityProperties;
            var mine = playerView.Entities.Where(e => e.PlayerId == me).ToList();
            var enemies = playerView.Entities.Where(e => e.PlayerId.HasValue && e.PlayerId != me).ToList();
            int resources = playerView.Players.First(p => p.Id == me).Resource;

            var count = new Dictionary<EntityType, int>();
            int CountOf(EntityType t) => count.TryGetValue(t, out var n) ? n : 0;
            foreach (var e in mine)
                count[e.EntityType] = CountOf(e.EntityType) + 1;
            // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
            int provided = mine.Where(e => e.Active).Sum(e => props[e.EntityType].PopulationProvide);
            int used = mine.Sum(e => props[e.EntityType].PopulationUse);

            var occupied = new HashSet<(int, int)>();
            foreach (var e in playerView.Entities)
            {
                int s = props[e.EntityType].Size;
                for (int dx = 0; dx < s; dx++)
                    for (int dy = 0; dy < s; dy++)
                        occupied.Add((e.Position.X + dx, e.Position.Y + dy));
            }

            // Can an entity of size `s` be placed with its lower-left corner at (x, y)?
            bool Free(int x, int y, int s)
            {
                for (int dx = 0; dx < s; dx++)
                    for (int dy = 0; dy < s; dy++)
                        if (x + dx < 0 || x + dx >= size || y + dy < 0 || y + dy >= size
                            || occupied.Contains((x + dx, y + dy)))
                            return false;
                return true;
            }

            // A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
            Vec2Int? SpotNextTo(Entity entity, int s)
            {
                int x = entity.Position.X, y = entity.Position.Y, es = props[entity.EntityType].Size;
                for (int k = 0; k < es; k++)
                    foreach (var (cx, cy) in new[] { (x + es, y + k), (x + k, y + es), (x - s, y + k), (x + k, y - s) })
                        if (Free(cx, cy, s))
                            return new Vec2Int(cx, cy);
                return null;
            }

            int Distance(Vec2Int a, Vec2Int b) => System.Math.Abs(a.X - b.X) + System.Math.Abs(a.Y - b.Y);

            Entity? Nearest(List<Entity> entities, Vec2Int position)
            {
                Entity? best = null;
                foreach (var candidate in entities)
                    if (!best.HasValue || Distance(candidate.Position, position) < Distance(best.Value.Position, position))
                        best = candidate;
                return best;
            }

            // what the builders should put up next: a missing base, then a house when the population is nearly full
            var wanted = BasesWanted.Where(t => CountOf(t) == 0).ToList();
            bool housePending = mine.Any(e => e.EntityType == EntityType.House && !e.Active);
            if (used + 3 > provided && !housePending)
                wanted.Add(EntityType.House);
            var damaged = mine.Where(e => !props[e.EntityType].CanMove && e.Health < props[e.EntityType].MaxHealth).ToList();
            var fighters = mine.Where(e => props[e.EntityType].CanMove && e.EntityType != EntityType.BuilderUnit).ToList();
            var home = mine.Where(e => !props[e.EntityType].CanMove).Select(e => (Vec2Int?)e.Position).FirstOrDefault()
                       ?? new Vec2Int(size / 2, size / 2);

            // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
            var builderBases = mine.Where(e => e.EntityType == EntityType.BuilderBase).ToList();
            var others = mine.Where(e => e.EntityType != EntityType.BuilderBase).ToList();
            var order = CountOf(EntityType.BuilderUnit) < FirstBuilders ? builderBases.Concat(others) : others.Concat(builderBases);

            var result = new Action(new Dictionary<int, EntityAction>());
            foreach (var e in order)
            {
                var p = props[e.EntityType];
                MoveAction? move = null;
                BuildAction? build = null;
                AttackAction? attack = null;
                RepairAction? repair = null;
                if (e.EntityType == EntityType.BuilderUnit)
                {
                    var target = Nearest(damaged, e.Position);
                    if (target.HasValue && Distance(target.Value.Position, e.Position) <= RepairRange)
                    {
                        move = new MoveAction(target.Value.Position, true, false);   // a repair needs an adjacent builder
                        repair = new RepairAction(target.Value.Id);
                    }
                    else
                    {
                        for (int i = 0; i < wanted.Count; i++)
                        {
                            var t = wanted[i];
                            var spot = SpotNextTo(e, props[t].Size);
                            if (spot.HasValue && resources >= props[t].InitialCost)
                            {
                                build = new BuildAction(t, spot.Value);
                                resources -= props[t].InitialCost;
                                wanted.RemoveAt(i);
                                break;
                            }
                        }
                        if (!build.HasValue)                                          // gather: the nearest resource, however far
                            attack = new AttackAction(null, new AutoAttack(size, new[] { EntityType.Resource }));
                    }
                }
                else if (p.CanMove)                                                   // a fighting unit
                {
                    var enemy = Nearest(enemies, e.Position);
                    if (fighters.Count >= ArmySize && enemy.HasValue)                 // the army is big enough: hunt
                        move = new MoveAction(enemy.Value.Position, true, true);
                    else                                                              // otherwise guard the base
                        move = new MoveAction(home, true, false);
                    attack = new AttackAction(null, new AutoAttack(p.SightRange, new EntityType[0]));
                }
                else if (p.Build.HasValue && e.Active)                                // a base: train its unit
                {
                    var unit = p.Build.Value.Options[0];
                    int cost = props[unit].InitialCost + CountOf(unit);               // a unit costs more the more you have
                    var spot = SpotNextTo(e, 1);
                    bool enough = unit == EntityType.BuilderUnit && CountOf(unit) >= MaxBuilders;
                    if (spot.HasValue && !enough && resources >= cost && used + props[unit].PopulationUse <= provided)
                    {
                        build = new BuildAction(unit, spot.Value);
                        resources -= cost;
                        used += props[unit].PopulationUse;
                        count[unit] = CountOf(unit) + 1;
                    }
                }
                else                                                                  // a turret shoots; houses and walls just stand
                {
                    attack = new AttackAction(null, new AutoAttack(p.SightRange, new EntityType[0]));
                }
                result.EntityActions[e.Id] = new EntityAction(move, build, attack, repair);
            }
            return result;
        }

        public void DebugUpdate(PlayerView playerView, DebugInterface debugInterface)
        {
            debugInterface.Send(new DebugCommand.Clear());
            debugInterface.GetState();
        }
    }
}
