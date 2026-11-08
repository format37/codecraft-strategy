// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

import model.*
import kotlin.math.abs

private val BASES_WANTED = listOf(EntityType.BUILDER_BASE, EntityType.RANGED_BASE)
private const val FIRST_BUILDERS = 5   // the builder base spends first until it has this many; then the fighting bases do
private const val MAX_BUILDERS = 12
private const val ARMY_SIZE = 8        // fighting units wait at home until there are this many of them
private const val REPAIR_RANGE = 6     // a builder this close to a damaged or unfinished building goes to repair it

private fun distance(a: Vec2Int, b: Vec2Int) = abs(a.x - b.x) + abs(a.y - b.y)

private fun nearest(entities: List<Entity>, position: Vec2Int) = entities.minByOrNull { distance(it.position, position) }

class MyStrategy {
    fun getAction(playerView: PlayerView, debugInterface: DebugInterface?): Action {
        val me = playerView.myId
        val size = playerView.mapSize
        val props = playerView.entityProperties
        val mine = playerView.entities.filter { it.playerId == me }
        val enemies = playerView.entities.filter { it.playerId != null && it.playerId != me }
        var resources = playerView.players.first { it.id == me }.resource

        val count = mine.groupingBy { it.entityType }.eachCount().toMutableMap()
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        val provided = mine.filter { it.active }.sumOf { props.getValue(it.entityType).populationProvide }
        var used = mine.sumOf { props.getValue(it.entityType).populationUse }

        val occupied = HashSet<Pair<Int, Int>>()
        for (e in playerView.entities) {
            val s = props.getValue(e.entityType).size
            for (dx in 0 until s) for (dy in 0 until s) occupied.add((e.position.x + dx) to (e.position.y + dy))
        }

        /** Can an entity of size `s` be placed with its lower-left corner at (x, y)? */
        fun free(x: Int, y: Int, s: Int) = (0 until s).all { dx ->
            (0 until s).all { dy -> x + dx in 0 until size && y + dy in 0 until size && ((x + dx) to (y + dy)) !in occupied }
        }

        /** A free place for a new entity of size `s` touching `entity` (right, top, left, bottom). */
        fun spotNextTo(entity: Entity, s: Int): Vec2Int? {
            val x = entity.position.x
            val y = entity.position.y
            val es = props.getValue(entity.entityType).size
            for (k in 0 until es) {
                for ((cx, cy) in listOf((x + es) to (y + k), (x + k) to (y + es), (x - s) to (y + k), (x + k) to (y - s))) {
                    if (free(cx, cy, s)) return Vec2Int(cx, cy)
                }
            }
            return null
        }

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        val wanted = BASES_WANTED.filter { (count[it] ?: 0) == 0 }.toMutableList()
        val housePending = mine.any { it.entityType == EntityType.HOUSE && !it.active }
        if (used + 3 > provided && !housePending) wanted.add(EntityType.HOUSE)
        val damaged = mine.filter { !props.getValue(it.entityType).canMove && it.health < props.getValue(it.entityType).maxHealth }
        val fighters = mine.filter { props.getValue(it.entityType).canMove && it.entityType != EntityType.BUILDER_UNIT }
        val home = mine.firstOrNull { !props.getValue(it.entityType).canMove }?.position ?: Vec2Int(size / 2, size / 2)

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        val (builderBases, others) = mine.partition { it.entityType == EntityType.BUILDER_BASE }
        val order = if ((count[EntityType.BUILDER_UNIT] ?: 0) < FIRST_BUILDERS) builderBases + others else others + builderBases

        val actions = mutableMapOf<Int, EntityAction>()
        for (e in order) {
            val p = props.getValue(e.entityType)
            var move: MoveAction? = null
            var build: BuildAction? = null
            var attack: AttackAction? = null
            var repair: RepairAction? = null
            val buildProps = p.build
            when {
                e.entityType == EntityType.BUILDER_UNIT -> {
                    val target = nearest(damaged, e.position)
                    if (target != null && distance(target.position, e.position) <= REPAIR_RANGE) {
                        move = MoveAction(target.position, true, false)   // a repair needs an adjacent builder
                        repair = RepairAction(target.id)
                    } else {
                        for (t in wanted) {
                            val spot = spotNextTo(e, props.getValue(t).size)
                            if (spot != null && resources >= props.getValue(t).initialCost) {
                                build = BuildAction(t, spot)
                                resources -= props.getValue(t).initialCost
                                wanted.remove(t)
                                break
                            }
                        }
                        if (build == null)                                 // gather: the nearest resource, however far
                            attack = AttackAction(null, AutoAttack(size, arrayOf(EntityType.RESOURCE)))
                    }
                }
                p.canMove -> {                                             // a fighting unit
                    val enemy = nearest(enemies, e.position)
                    move = if (fighters.size >= ARMY_SIZE && enemy != null) {
                        MoveAction(enemy.position, true, true)             // the army is big enough: hunt
                    } else {
                        MoveAction(home, true, false)                      // otherwise guard the base
                    }
                    attack = AttackAction(null, AutoAttack(p.sightRange, emptyArray()))
                }
                buildProps != null && e.active -> {                        // a base: train its unit
                    val unit = buildProps.options[0]
                    val cost = props.getValue(unit).initialCost + (count[unit] ?: 0)   // a unit costs more the more you have
                    val spot = spotNextTo(e, 1)
                    val enough = unit == EntityType.BUILDER_UNIT && (count[unit] ?: 0) >= MAX_BUILDERS
                    if (spot != null && !enough && resources >= cost && used + props.getValue(unit).populationUse <= provided) {
                        build = BuildAction(unit, spot)
                        resources -= cost
                        used += props.getValue(unit).populationUse
                        count[unit] = (count[unit] ?: 0) + 1
                    }
                }
                else -> attack = AttackAction(null, AutoAttack(p.sightRange, emptyArray()))   // a turret shoots; houses and walls just stand
            }
            actions[e.id] = EntityAction(move, build, attack, repair)
        }
        return Action(actions)
    }

    fun debugUpdate(playerView: PlayerView, debugInterface: DebugInterface) {
        debugInterface.send(model.DebugCommand.Clear())
        debugInterface.getState()
    }
}
