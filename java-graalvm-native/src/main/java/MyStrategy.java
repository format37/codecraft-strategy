// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

import model.*;

import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

public class MyStrategy {
    private static final EntityType[] BASES_WANTED = {EntityType.BUILDER_BASE, EntityType.RANGED_BASE};
    private static final int FIRST_BUILDERS = 5;  // the builder base spends first until it has this many; then the fighting bases do
    private static final int MAX_BUILDERS = 12;
    private static final int ARMY_SIZE = 8;       // fighting units wait at home until there are this many of them
    private static final int REPAIR_RANGE = 6;    // a builder this close to a damaged or unfinished building goes to repair it

    private static final EntityType[] ALL_TARGETS = new EntityType[0];
    private static final EntityType[] RESOURCES_ONLY = {EntityType.RESOURCE};

    // per-tick state shared with the helpers below
    private int size;
    private Map<EntityType, EntityProperties> props;
    private boolean[][] occupied;

    public Action getAction(PlayerView playerView, DebugInterface debugInterface) {
        int me = playerView.getMyId();
        size = playerView.getMapSize();
        props = playerView.getEntityProperties();
        List<Entity> mine = new ArrayList<>();
        List<Entity> enemies = new ArrayList<>();
        for (Entity e : playerView.getEntities()) {
            if (e.getPlayerId() == null) {
                continue;
            }
            if (e.getPlayerId() == me) {
                mine.add(e);
            } else {
                enemies.add(e);
            }
        }
        int resources = 0;
        for (Player p : playerView.getPlayers()) {
            if (p.getId() == me) {
                resources = p.getResource();
            }
        }

        Map<EntityType, Integer> count = new EnumMap<>(EntityType.class);
        for (Entity e : mine) {
            count.merge(e.getEntityType(), 1, Integer::sum);
        }
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        int provided = 0;
        int used = 0;
        for (Entity e : mine) {
            if (e.isActive()) {
                provided += props.get(e.getEntityType()).getPopulationProvide();
            }
            used += props.get(e.getEntityType()).getPopulationUse();
        }

        occupied = new boolean[size][size];
        for (Entity e : playerView.getEntities()) {
            int s = props.get(e.getEntityType()).getSize();
            for (int dx = 0; dx < s; dx++) {
                for (int dy = 0; dy < s; dy++) {
                    int x = e.getPosition().getX() + dx;
                    int y = e.getPosition().getY() + dy;
                    if (inside(x, y)) {
                        occupied[x][y] = true;
                    }
                }
            }
        }

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        List<EntityType> wanted = new ArrayList<>();
        for (EntityType t : BASES_WANTED) {
            if (count.getOrDefault(t, 0) == 0) {
                wanted.add(t);
            }
        }
        boolean housePending = false;
        for (Entity e : mine) {
            if (e.getEntityType() == EntityType.HOUSE && !e.isActive()) {
                housePending = true;
            }
        }
        if (used + 3 > provided && !housePending) {
            wanted.add(EntityType.HOUSE);
        }
        List<Entity> damaged = new ArrayList<>();
        List<Entity> fighters = new ArrayList<>();
        Vec2Int home = null;
        for (Entity e : mine) {
            EntityProperties p = props.get(e.getEntityType());
            if (!p.isCanMove() && e.getHealth() < p.getMaxHealth()) {
                damaged.add(e);
            }
            if (p.isCanMove() && e.getEntityType() != EntityType.BUILDER_UNIT) {
                fighters.add(e);
            }
            if (!p.isCanMove() && home == null) {
                home = e.getPosition();
            }
        }
        if (home == null) {
            home = new Vec2Int(size / 2, size / 2);
        }

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        List<Entity> builderBases = new ArrayList<>();
        List<Entity> others = new ArrayList<>();
        for (Entity e : mine) {
            (e.getEntityType() == EntityType.BUILDER_BASE ? builderBases : others).add(e);
        }
        List<Entity> order = new ArrayList<>();
        if (count.getOrDefault(EntityType.BUILDER_UNIT, 0) < FIRST_BUILDERS) {
            order.addAll(builderBases);
            order.addAll(others);
        } else {
            order.addAll(others);
            order.addAll(builderBases);
        }

        Action result = new Action(new HashMap<>());
        for (Entity e : order) {
            EntityProperties p = props.get(e.getEntityType());
            MoveAction move = null;
            BuildAction build = null;
            AttackAction attack = null;
            RepairAction repair = null;
            if (e.getEntityType() == EntityType.BUILDER_UNIT) {
                Entity target = nearest(damaged, e.getPosition());
                if (target != null && distance(target.getPosition(), e.getPosition()) <= REPAIR_RANGE) {
                    move = new MoveAction(target.getPosition(), true, false);  // a repair needs an adjacent builder
                    repair = new RepairAction(target.getId());
                } else {
                    for (Iterator<EntityType> it = wanted.iterator(); it.hasNext(); ) {
                        EntityType t = it.next();
                        Vec2Int spot = spotNextTo(e, props.get(t).getSize());
                        if (spot != null && resources >= props.get(t).getInitialCost()) {
                            build = new BuildAction(t, spot);
                            resources -= props.get(t).getInitialCost();
                            it.remove();
                            break;
                        }
                    }
                    if (build == null) {                                       // gather: the nearest resource, however far
                        attack = new AttackAction(null, new AutoAttack(size, RESOURCES_ONLY));
                    }
                }
            } else if (p.isCanMove()) {                                        // a fighting unit
                Entity enemy = nearest(enemies, e.getPosition());
                if (fighters.size() >= ARMY_SIZE && enemy != null) {           // the army is big enough: hunt
                    move = new MoveAction(enemy.getPosition(), true, true);
                } else {                                                       // otherwise guard the base
                    move = new MoveAction(home, true, false);
                }
                attack = new AttackAction(null, new AutoAttack(p.getSightRange(), ALL_TARGETS));
            } else if (p.getBuild() != null && e.isActive()) {                 // a base: train its unit
                EntityType unit = p.getBuild().getOptions()[0];
                int have = count.getOrDefault(unit, 0);
                int cost = props.get(unit).getInitialCost() + have;            // a unit costs more the more you have
                Vec2Int spot = spotNextTo(e, 1);
                boolean enough = unit == EntityType.BUILDER_UNIT && have >= MAX_BUILDERS;
                if (spot != null && !enough && resources >= cost
                        && used + props.get(unit).getPopulationUse() <= provided) {
                    build = new BuildAction(unit, spot);
                    resources -= cost;
                    used += props.get(unit).getPopulationUse();
                    count.put(unit, have + 1);
                }
            } else {                                                           // a turret shoots; houses and walls just stand
                attack = new AttackAction(null, new AutoAttack(p.getSightRange(), ALL_TARGETS));
            }
            result.getEntityActions().put(e.getId(), new EntityAction(move, build, attack, repair));
        }
        return result;
    }

    private boolean inside(int x, int y) {
        return 0 <= x && x < size && 0 <= y && y < size;
    }

    /** Can an entity of size {@code s} be placed with its lower-left corner at (x, y)? */
    private boolean free(int x, int y, int s) {
        for (int dx = 0; dx < s; dx++) {
            for (int dy = 0; dy < s; dy++) {
                if (!inside(x + dx, y + dy) || occupied[x + dx][y + dy]) {
                    return false;
                }
            }
        }
        return true;
    }

    /** A free place for a new entity of size {@code s} touching {@code entity} (right, top, left, bottom). */
    private Vec2Int spotNextTo(Entity entity, int s) {
        int x = entity.getPosition().getX();
        int y = entity.getPosition().getY();
        int es = props.get(entity.getEntityType()).getSize();
        for (int k = 0; k < es; k++) {
            int[][] candidates = {{x + es, y + k}, {x + k, y + es}, {x - s, y + k}, {x + k, y - s}};
            for (int[] c : candidates) {
                if (free(c[0], c[1], s)) {
                    return new Vec2Int(c[0], c[1]);
                }
            }
        }
        return null;
    }

    private static int distance(Vec2Int a, Vec2Int b) {
        return Math.abs(a.getX() - b.getX()) + Math.abs(a.getY() - b.getY());
    }

    private static Entity nearest(List<Entity> entities, Vec2Int position) {
        Entity best = null;
        for (Entity e : entities) {
            if (best == null || distance(e.getPosition(), position) < distance(best.getPosition(), position)) {
                best = e;
            }
        }
        return best;
    }

    public void debugUpdate(PlayerView playerView, DebugInterface debugInterface) {
        debugInterface.send(new DebugCommand.Clear());
        debugInterface.getState();
    }
}
