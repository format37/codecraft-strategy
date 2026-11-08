# A starter strategy for CodeCraft 2020: builders gather resources, repair the base
# and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
# train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
# enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
# Make it yours.

require 'set'
require_relative 'model'

class MyStrategy
  BASES_WANTED = [EntityType::BUILDER_BASE, EntityType::RANGED_BASE].freeze
  FIRST_BUILDERS = 5        # the builder base spends first until it has this many; then the fighting bases do
  MAX_BUILDERS = 12
  ARMY_SIZE = 8             # fighting units wait at home until there are this many of them
  REPAIR_RANGE = 6          # a builder this close to a damaged or unfinished building goes to repair it

  def get_action(player_view, debug_interface)
    me = player_view.my_id
    @size = player_view.map_size
    @props = player_view.entity_properties
    mine = player_view.entities.select { |e| e.player_id == me }
    enemies = player_view.entities.select { |e| e.player_id && e.player_id != me }
    resources = player_view.players.find { |p| p.id == me }.resource

    count = mine.each_with_object(Hash.new(0)) { |e, h| h[e.entity_type] += 1 }
    # population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
    provided = mine.select(&:active).sum { |e| @props[e.entity_type].population_provide }
    used = mine.sum { |e| @props[e.entity_type].population_use }

    @occupied = Set.new
    player_view.entities.each do |e|
      s = @props[e.entity_type].size
      s.times { |dx| s.times { |dy| @occupied << [e.position.x + dx, e.position.y + dy] } }
    end

    # what the builders should put up next: a missing base, then a house when the population is nearly full
    wanted = BASES_WANTED.select { |t| count[t].zero? }
    house_pending = mine.any? { |e| e.entity_type == EntityType::HOUSE && !e.active }
    wanted << EntityType::HOUSE if used + 3 > provided && !house_pending
    damaged = mine.select { |e| !@props[e.entity_type].can_move && e.health < @props[e.entity_type].max_health }
    fighters = mine.select { |e| @props[e.entity_type].can_move && e.entity_type != EntityType::BUILDER_UNIT }
    home = mine.find { |e| !@props[e.entity_type].can_move }&.position || Vec2Int.new(@size / 2, @size / 2)

    # who spends first: the builder base while builders are few, the fighting bases (and houses) after that
    builder_bases, others = mine.partition { |e| e.entity_type == EntityType::BUILDER_BASE }
    order = count[EntityType::BUILDER_UNIT] < FIRST_BUILDERS ? builder_bases + others : others + builder_bases

    actions = {}
    order.each do |e|
      p = @props[e.entity_type]
      move = build = attack = repair = nil
      if e.entity_type == EntityType::BUILDER_UNIT
        target = nearest(damaged, e.position)
        if target && distance(target.position, e.position) <= REPAIR_RANGE
          move = MoveAction.new(target.position, true, false)        # a repair needs an adjacent builder
          repair = RepairAction.new(target.id)
        else
          wanted.each do |t|
            spot = spot_next_to(e, @props[t].size)
            next unless spot && resources >= @props[t].initial_cost
            build = BuildAction.new(t, spot)
            resources -= @props[t].initial_cost
            wanted.delete(t)
            break
          end
          # gather: the nearest resource, however far
          attack = AttackAction.new(nil, AutoAttack.new(@size, [EntityType::RESOURCE])) if build.nil?
        end
      elsif p.can_move                                               # a fighting unit
        enemy = nearest(enemies, e.position)
        if fighters.size >= ARMY_SIZE && enemy                       # the army is big enough: hunt
          move = MoveAction.new(enemy.position, true, true)
        else                                                         # otherwise guard the base
          move = MoveAction.new(home, true, false)
        end
        attack = AttackAction.new(nil, AutoAttack.new(p.sight_range, []))
      elsif p.build && e.active                                      # a base: train its unit
        unit = p.build.options[0]
        cost = @props[unit].initial_cost + count[unit]               # a unit costs more the more you have
        spot = spot_next_to(e, 1)
        enough = unit == EntityType::BUILDER_UNIT && count[unit] >= MAX_BUILDERS
        if spot && !enough && resources >= cost && used + @props[unit].population_use <= provided
          build = BuildAction.new(unit, spot)
          resources -= cost
          used += @props[unit].population_use
          count[unit] += 1
        end
      else                                                           # a turret shoots; houses and walls just stand
        attack = AttackAction.new(nil, AutoAttack.new(p.sight_range, []))
      end
      actions[e.id] = EntityAction.new(move, build, attack, repair)
    end
    Action.new(actions)
  end

  def debug_update(player_view, debug_interface)
    debug_interface.send(DebugCommand::Clear.new())
    debug_interface.get_state()
  end

  private

  # Can an entity of size `s` be placed with its lower-left corner at (x, y)?
  def free?(x, y, s)
    (0...s).all? do |dx|
      (0...s).all? do |dy|
        cx, cy = x + dx, y + dy
        cx.between?(0, @size - 1) && cy.between?(0, @size - 1) && !@occupied.include?([cx, cy])
      end
    end
  end

  # A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
  def spot_next_to(entity, s)
    x, y, es = entity.position.x, entity.position.y, @props[entity.entity_type].size
    es.times do |k|
      [[x + es, y + k], [x + k, y + es], [x - s, y + k], [x + k, y - s]].each do |cx, cy|
        return Vec2Int.new(cx, cy) if free?(cx, cy, s)
      end
    end
    nil
  end

  def distance(a, b)
    (a.x - b.x).abs + (a.y - b.y).abs
  end

  def nearest(entities, position)
    entities.min_by { |e| distance(e.position, position) }
  end
end
