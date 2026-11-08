// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

const model = require('./model/index');
const { EntityType, Vec2Int, MoveAction, BuildAction, AttackAction, AutoAttack, RepairAction, EntityAction, Action } = model;

const BASES_WANTED = [EntityType.BuilderBase, EntityType.RangedBase];
const FIRST_BUILDERS = 5;        // the builder base spends first until it has this many; then the fighting bases do
const MAX_BUILDERS = 12;
const ARMY_SIZE = 8;             // fighting units wait at home until there are this many of them
const REPAIR_RANGE = 6;          // a builder this close to a damaged or unfinished building goes to repair it

const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

/** The first of `entities` closest to `position`, or null when there are none. */
function nearest(entities, position) {
    let best = null;
    for (const e of entities) {
        if (best === null || distance(e.position, position) < distance(best.position, position)) best = e;
    }
    return best;
}

class MyStrategy {
    async getAction(playerView, debugInterface) {
        const me = playerView.myId;
        const size = playerView.mapSize;
        const props = playerView.entityProperties;                 // Map: EntityType -> EntityProperties
        const mine = playerView.entities.filter(e => e.playerId === me);
        const enemies = playerView.entities.filter(e => e.playerId !== null && e.playerId !== me);
        let resources = playerView.players.find(p => p.id === me).resource;

        const count = new Map();
        for (const e of mine) count.set(e.entityType, (count.get(e.entityType) || 0) + 1);
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        const provided = mine.filter(e => e.active).reduce((sum, e) => sum + props.get(e.entityType).populationProvide, 0);
        let used = mine.reduce((sum, e) => sum + props.get(e.entityType).populationUse, 0);

        const cell = (x, y) => x * size + y;                        // a map cell as a Set key
        const occupied = new Set();
        for (const e of playerView.entities) {
            const s = props.get(e.entityType).size;
            for (let dx = 0; dx < s; dx++) {
                for (let dy = 0; dy < s; dy++) occupied.add(cell(e.position.x + dx, e.position.y + dy));
            }
        }

        /** Can an entity of size `s` be placed with its lower-left corner at (x, y)? */
        const free = (x, y, s) => {
            for (let dx = 0; dx < s; dx++) {
                for (let dy = 0; dy < s; dy++) {
                    const cx = x + dx, cy = y + dy;
                    if (cx < 0 || cx >= size || cy < 0 || cy >= size || occupied.has(cell(cx, cy))) return false;
                }
            }
            return true;
        };

        /** A free place for a new entity of size `s` touching `entity` (right, top, left, bottom). */
        const spotNextTo = (entity, s) => {
            const { x, y } = entity.position;
            const es = props.get(entity.entityType).size;
            for (let k = 0; k < es; k++) {
                for (const [cx, cy] of [[x + es, y + k], [x + k, y + es], [x - s, y + k], [x + k, y - s]]) {
                    if (free(cx, cy, s)) return new Vec2Int(cx, cy);
                }
            }
            return null;
        };

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        const wanted = BASES_WANTED.filter(t => !count.get(t));
        const housePending = mine.some(e => e.entityType === EntityType.House && !e.active);
        if (used + 3 > provided && !housePending) wanted.push(EntityType.House);
        const damaged = mine.filter(e => !props.get(e.entityType).canMove && e.health < props.get(e.entityType).maxHealth);
        const fighters = mine.filter(e => props.get(e.entityType).canMove && e.entityType !== EntityType.BuilderUnit);
        const building = mine.find(e => !props.get(e.entityType).canMove);
        const home = building ? building.position : new Vec2Int(Math.floor(size / 2), Math.floor(size / 2));

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        const builderBases = mine.filter(e => e.entityType === EntityType.BuilderBase);
        const others = mine.filter(e => e.entityType !== EntityType.BuilderBase);
        const order = (count.get(EntityType.BuilderUnit) || 0) < FIRST_BUILDERS ? builderBases.concat(others) : others.concat(builderBases);

        const result = new Action(new Map());
        for (const e of order) {
            const p = props.get(e.entityType);
            let move = null, build = null, attack = null, repair = null;
            if (e.entityType === EntityType.BuilderUnit) {
                const target = nearest(damaged, e.position);
                if (target !== null && distance(target.position, e.position) <= REPAIR_RANGE) {
                    move = new MoveAction(target.position, true, false);   // a repair needs an adjacent builder
                    repair = new RepairAction(target.id);
                } else {
                    for (const t of wanted) {
                        const spot = spotNextTo(e, props.get(t).size);
                        if (spot !== null && resources >= props.get(t).initialCost) {
                            build = new BuildAction(t, spot);
                            resources -= props.get(t).initialCost;
                            wanted.splice(wanted.indexOf(t), 1);
                            break;
                        }
                    }
                    if (build === null) {                                  // gather: the nearest resource, however far
                        attack = new AttackAction(null, new AutoAttack(size, [EntityType.Resource]));
                    }
                }
            } else if (p.canMove) {                                        // a fighting unit
                const enemy = nearest(enemies, e.position);
                if (fighters.length >= ARMY_SIZE && enemy !== null) {      // the army is big enough: hunt
                    move = new MoveAction(enemy.position, true, true);
                } else {                                                   // otherwise guard the base
                    move = new MoveAction(home, true, false);
                }
                attack = new AttackAction(null, new AutoAttack(p.sightRange, []));
            } else if (p.build !== null && e.active) {                     // a base: train its unit
                const unit = p.build.options[0];
                const cost = props.get(unit).initialCost + (count.get(unit) || 0);   // a unit costs more the more you have
                const spot = spotNextTo(e, 1);
                const enough = unit === EntityType.BuilderUnit && (count.get(unit) || 0) >= MAX_BUILDERS;
                if (spot !== null && !enough && resources >= cost && used + props.get(unit).populationUse <= provided) {
                    build = new BuildAction(unit, spot);
                    resources -= cost;
                    used += props.get(unit).populationUse;
                    count.set(unit, (count.get(unit) || 0) + 1);
                }
            } else {                                                       // a turret shoots; houses and walls just stand
                attack = new AttackAction(null, new AutoAttack(p.sightRange, []));
            }
            result.entityActions.set(e.id, new EntityAction(move, build, attack, repair));
        }
        return result;
    }

    async debugUpdate(playerView, debugInterface) {
        await debugInterface.send(new model.DebugCommand.Clear());
        await debugInterface.getState();
    }
}

module.exports.MyStrategy = MyStrategy;
