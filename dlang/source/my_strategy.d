// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

import model;
import debug_interface;
import std.algorithm;
import std.array;
import std.math : abs;
import std.range;
import std.typecons;

enum BASES_WANTED = [EntityType.BuilderBase, EntityType.RangedBase];
enum FIRST_BUILDERS = 5;  // the builder base spends first until it has this many; then the fighting bases do
enum MAX_BUILDERS = 12;
enum ARMY_SIZE = 8;       // fighting units wait at home until there are this many of them
enum REPAIR_RANGE = 6;    // a builder this close to a damaged or unfinished building goes to repair it

class MyStrategy
{
    Action getAction(PlayerView playerView, DebugInterface debugInterface)
    {
        const me = playerView.myId;
        const size = playerView.mapSize;
        auto props = playerView.entityProperties;
        auto mine = playerView.entities.filter!(e => !e.playerId.isNull && e.playerId.get == me).array;
        auto enemies = playerView.entities.filter!(e => !e.playerId.isNull && e.playerId.get != me).array;
        int resources = playerView.players.find!(p => p.id == me).front.resource;

        int[EntityType] count;
        foreach (e; mine)
            count[e.entityType]++;
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        int provided = mine.filter!(e => e.active).map!(e => props[e.entityType].populationProvide).sum;
        int used = mine.map!(e => props[e.entityType].populationUse).sum;

        bool[Vec2Int] occupied;
        foreach (e; playerView.entities)
        {
            const s = props[e.entityType].size;
            foreach (dx; 0 .. s)
                foreach (dy; 0 .. s)
                    occupied[Vec2Int(e.position.x + dx, e.position.y + dy)] = true;
        }

        // Can an entity of size `s` be placed with its lower-left corner at (x, y)?
        bool free(int x, int y, int s)
        {
            foreach (dx; 0 .. s)
                foreach (dy; 0 .. s)
                    if (x + dx < 0 || x + dx >= size || y + dy < 0 || y + dy >= size
                            || (Vec2Int(x + dx, y + dy) in occupied) !is null)
                        return false;
            return true;
        }

        // A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
        Nullable!Vec2Int spotNextTo(Entity entity, int s)
        {
            const x = entity.position.x, y = entity.position.y, es = props[entity.entityType].size;
            foreach (k; 0 .. es)
            {
                Vec2Int[4] candidates = [Vec2Int(x + es, y + k), Vec2Int(x + k, y + es),
                                         Vec2Int(x - s, y + k), Vec2Int(x + k, y - s)];
                foreach (c; candidates)
                    if (free(c.x, c.y, s))
                        return nullable(c);
            }
            return Nullable!Vec2Int.init;
        }

        int distance(Vec2Int a, Vec2Int b)
        {
            return abs(a.x - b.x) + abs(a.y - b.y);
        }

        // The entity closest to `position` (Manhattan), null when there is none.
        Entity* nearest(Entity[] entities, Vec2Int position)
        {
            Entity* best = null;
            foreach (ref e; entities)
                if (best is null || distance(e.position, position) < distance(best.position, position))
                    best = &e;
            return best;
        }

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        auto wanted = BASES_WANTED.filter!(t => !count.get(t, 0)).array;
        const housePending = mine.any!(e => e.entityType == EntityType.House && !e.active);
        if (used + 3 > provided && !housePending)
            wanted ~= EntityType.House;
        auto damaged = mine.filter!(e => !props[e.entityType].canMove && e.health < props[e.entityType].maxHealth).array;
        auto fighters = mine.filter!(e => props[e.entityType].canMove && e.entityType != EntityType.BuilderUnit).array;
        auto buildings = mine.find!(e => !props[e.entityType].canMove);
        auto home = buildings.empty ? Vec2Int(size / 2, size / 2) : buildings.front.position;

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        auto builderBases = mine.filter!(e => e.entityType == EntityType.BuilderBase).array;
        auto others = mine.filter!(e => e.entityType != EntityType.BuilderBase).array;
        auto order = count.get(EntityType.BuilderUnit, 0) < FIRST_BUILDERS ? builderBases ~ others : others ~ builderBases;

        EntityAction[int] actions;
        foreach (e; order)
        {
            auto p = props[e.entityType];
            Nullable!MoveAction move;
            Nullable!BuildAction build;
            Nullable!AttackAction attack;
            Nullable!RepairAction repair;
            if (e.entityType == EntityType.BuilderUnit)
            {
                auto target = nearest(damaged, e.position);
                if (target !is null && distance(target.position, e.position) <= REPAIR_RANGE)
                {
                    move = MoveAction(target.position, true, false);     // a repair needs an adjacent builder
                    repair = RepairAction(target.id);
                }
                else
                {
                    foreach (i, t; wanted)
                    {
                        auto spot = spotNextTo(e, props[t].size);
                        if (!spot.isNull && resources >= props[t].initialCost)
                        {
                            build = BuildAction(t, spot.get);
                            resources -= props[t].initialCost;
                            wanted = wanted.remove(i);
                            break;
                        }
                    }
                    if (build.isNull)                                  // gather: the nearest resource, however far
                        attack = AttackAction(Nullable!int.init, nullable(AutoAttack(size, [EntityType.Resource])));
                }
            }
            else if (p.canMove)                                            // a fighting unit
            {
                auto enemy = nearest(enemies, e.position);
                if (fighters.length >= ARMY_SIZE && enemy !is null)        // the army is big enough: hunt
                    move = MoveAction(enemy.position, true, true);
                else                                                       // otherwise guard the base
                    move = MoveAction(home, true, false);
                attack = AttackAction(Nullable!int.init, nullable(AutoAttack(p.sightRange, [])));
            }
            else if (!p.build.isNull && e.active)                          // a base: train its unit
            {
                auto unit = p.build.get.options[0];
                const cost = props[unit].initialCost + count.get(unit, 0);   // a unit costs more the more you have
                auto spot = spotNextTo(e, 1);
                const enough = unit == EntityType.BuilderUnit && count.get(unit, 0) >= MAX_BUILDERS;
                if (!spot.isNull && !enough && resources >= cost && used + props[unit].populationUse <= provided)
                {
                    build = BuildAction(unit, spot.get);
                    resources -= cost;
                    used += props[unit].populationUse;
                    count[unit]++;
                }
            }
            else                                                           // a turret shoots; houses and walls just stand
                attack = AttackAction(Nullable!int.init, nullable(AutoAttack(p.sightRange, [])));
            actions[e.id] = EntityAction(move, build, attack, repair);
        }
        return Action(actions);
    }

    void debugUpdate(PlayerView playerView, DebugInterface debugInterface)
    {
        debugInterface.send(new DebugCommand.Clear());
        debugInterface.getState();
    }
}
