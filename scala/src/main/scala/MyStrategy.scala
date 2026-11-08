// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

import model._
import scala.collection.mutable

object MyStrategy {
  val BASES_WANTED: Seq[EntityType] = Seq(EntityType.BUILDER_BASE, EntityType.RANGED_BASE)
  val FIRST_BUILDERS = 5        // the builder base spends first until it has this many; then the fighting bases do
  val MAX_BUILDERS = 12
  val ARMY_SIZE = 8             // fighting units wait at home until there are this many of them
  val REPAIR_RANGE = 6          // a builder this close to a damaged or unfinished building goes to repair it
}

class MyStrategy {
  import MyStrategy._

  def getAction(playerView: PlayerView, debugInterface: Option[DebugInterface]): Action = {
    val me = playerView.myId
    val size = playerView.mapSize
    val props = playerView.entityProperties
    val mine = playerView.entities.filter(_.playerId.contains(me))
    val enemies = playerView.entities.filter(e => e.playerId.exists(_ != me))
    var resources = playerView.players.find(_.id == me).get.resource

    val count = mutable.Map[EntityType, Int]().withDefaultValue(0)
    for (e <- mine) count(e.entityType) += 1
    // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
    val provided = mine.filter(_.active).map(e => props(e.entityType).populationProvide).sum
    var used = mine.map(e => props(e.entityType).populationUse).sum

    val occupied = mutable.Set[(Int, Int)]()
    for (e <- playerView.entities; s = props(e.entityType).size; dx <- 0 until s; dy <- 0 until s)
      occupied += ((e.position.x + dx, e.position.y + dy))

    /** Can an entity of size `s` be placed with its lower-left corner at (x, y)? */
    def free(x: Int, y: Int, s: Int): Boolean =
      (0 until s).forall(dx => (0 until s).forall(dy =>
        0 <= x + dx && x + dx < size && 0 <= y + dy && y + dy < size && !occupied.contains((x + dx, y + dy))))

    /** A free place for a new entity of size `s` touching `entity` (right, top, left, bottom). */
    def spotNextTo(entity: Entity, s: Int): Option[Vec2Int] = {
      val (x, y, es) = (entity.position.x, entity.position.y, props(entity.entityType).size)
      (0 until es).iterator
        .flatMap(k => Seq((x + es, y + k), (x + k, y + es), (x - s, y + k), (x + k, y - s)))
        .collectFirst { case (cx, cy) if free(cx, cy, s) => Vec2Int(cx, cy) }
    }

    def distance(a: Vec2Int, b: Vec2Int): Int = (a.x - b.x).abs + (a.y - b.y).abs

    def nearest(entities: Seq[Entity], position: Vec2Int): Option[Entity] =
      entities.minByOption(e => distance(e.position, position))

    // what the builders should put up next: a missing base, then a house when the population is nearly full
    val wanted = mutable.ListBuffer.from(BASES_WANTED.filter(t => count(t) == 0))
    val housePending = mine.exists(e => e.entityType == EntityType.HOUSE && !e.active)
    if (used + 3 > provided && !housePending) wanted += EntityType.HOUSE
    val damaged = mine.filter(e => !props(e.entityType).canMove && e.health < props(e.entityType).maxHealth)
    val fighters = mine.filter(e => props(e.entityType).canMove && e.entityType != EntityType.BUILDER_UNIT)
    val home = mine.find(e => !props(e.entityType).canMove).map(_.position).getOrElse(Vec2Int(size / 2, size / 2))

    // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
    val builderBases = mine.filter(_.entityType == EntityType.BUILDER_BASE)
    val others = mine.filter(_.entityType != EntityType.BUILDER_BASE)
    val order = if (count(EntityType.BUILDER_UNIT) < FIRST_BUILDERS) builderBases ++ others else others ++ builderBases

    val result = mutable.Map[Int, EntityAction]()
    for (e <- order) {
      val p = props(e.entityType)
      var move: Option[MoveAction] = None
      var build: Option[BuildAction] = None
      var attack: Option[AttackAction] = None
      var repair: Option[RepairAction] = None
      if (e.entityType == EntityType.BUILDER_UNIT) {
        nearest(damaged, e.position) match {
          case Some(target) if distance(target.position, e.position) <= REPAIR_RANGE =>
            move = Some(MoveAction(target.position, true, false))     // a repair needs an adjacent builder
            repair = Some(RepairAction(target.id))
          case _ =>
            val choice = wanted.iterator.map(t => (t, spotNextTo(e, props(t).size)))
              .collectFirst { case (t, Some(spot)) if resources >= props(t).initialCost => (t, spot) }
            choice.foreach { case (t, spot) =>
              build = Some(BuildAction(t, spot))
              resources -= props(t).initialCost
              wanted -= t
            }
            if (build.isEmpty)                                         // gather: the nearest resource, however far
              attack = Some(AttackAction(None, Some(AutoAttack(size, Seq(EntityType.RESOURCE)))))
        }
      } else if (p.canMove) {                                          // a fighting unit
        move = Some(nearest(enemies, e.position) match {
          case Some(enemy) if fighters.size >= ARMY_SIZE =>            // the army is big enough: hunt
            MoveAction(enemy.position, true, true)
          case _ =>                                                    // otherwise guard the base
            MoveAction(home, true, false)
        })
        attack = Some(AttackAction(None, Some(AutoAttack(p.sightRange, Seq()))))
      } else p.build match {
        case Some(b) if e.active =>                                    // a base: train its unit
          val unit = b.options.head
          val cost = props(unit).initialCost + count(unit)             // a unit costs more the more you have
          val spot = spotNextTo(e, 1)
          val enough = unit == EntityType.BUILDER_UNIT && count(unit) >= MAX_BUILDERS
          if (spot.isDefined && !enough && resources >= cost && used + props(unit).populationUse <= provided) {
            build = Some(BuildAction(unit, spot.get))
            resources -= cost
            used += props(unit).populationUse
            count(unit) += 1
          }
        case _ =>                                                      // a turret shoots; houses and walls just stand
          attack = Some(AttackAction(None, Some(AutoAttack(p.sightRange, Seq()))))
      }
      result(e.id) = EntityAction(move, build, attack, repair)
    }
    Action(result.toMap)
  }

  def debugUpdate(playerView: PlayerView, debugInterface: DebugInterface): Unit = {
    debugInterface.send(DebugCommand.Clear())
    debugInterface.getState()
  }
}
