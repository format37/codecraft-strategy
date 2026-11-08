// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

package main

import (
	. "aicup2020/model"
)

var BASES_WANTED = []EntityType{EntityTypeBuilderBase, EntityTypeRangedBase}

const (
	FIRST_BUILDERS = 5  // the builder base spends first until it has this many; then the fighting bases do
	MAX_BUILDERS   = 12
	ARMY_SIZE      = 8  // fighting units wait at home until there are this many of them
	REPAIR_RANGE   = 6  // a builder this close to a damaged or unfinished building goes to repair it
)

type MyStrategy struct{}

func NewMyStrategy() MyStrategy {
	return MyStrategy{}
}

func abs(v int32) int32 {
	if v < 0 {
		return -v
	}
	return v
}

func distance(a, b Vec2Int32) int32 {
	return abs(a.X-b.X) + abs(a.Y-b.Y)
}

// nearest returns the entity closest to position (Manhattan distance), nil when there is none.
func nearest(entities []Entity, position Vec2Int32) *Entity {
	var best *Entity
	for i := range entities {
		if best == nil || distance(entities[i].Position, position) < distance(best.Position, position) {
			best = &entities[i]
		}
	}
	return best
}

func (strategy MyStrategy) getAction(playerView PlayerView, debugInterface *DebugInterface) Action {
	me := playerView.MyId
	size := playerView.MapSize
	props := playerView.EntityProperties
	var mine, enemies []Entity
	for _, e := range playerView.Entities {
		switch {
		case e.PlayerId == nil:
		case *e.PlayerId == me:
			mine = append(mine, e)
		default:
			enemies = append(enemies, e)
		}
	}
	var resources int32
	for _, p := range playerView.Players {
		if p.Id == me {
			resources = p.Resource
			break
		}
	}

	count := make(map[EntityType]int32)
	// population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
	var provided, used int32
	for _, e := range mine {
		count[e.EntityType]++
		if e.Active {
			provided += props[e.EntityType].PopulationProvide
		}
		used += props[e.EntityType].PopulationUse
	}

	occupied := make(map[Vec2Int32]struct{})
	for _, e := range playerView.Entities {
		s := props[e.EntityType].Size
		for dx := int32(0); dx < s; dx++ {
			for dy := int32(0); dy < s; dy++ {
				occupied[Vec2Int32{X: e.Position.X + dx, Y: e.Position.Y + dy}] = struct{}{}
			}
		}
	}

	// free: can an entity of size s be placed with its lower-left corner at (x, y)?
	free := func(x, y, s int32) bool {
		for dx := int32(0); dx < s; dx++ {
			for dy := int32(0); dy < s; dy++ {
				cx, cy := x+dx, y+dy
				if cx < 0 || cx >= size || cy < 0 || cy >= size {
					return false
				}
				if _, taken := occupied[Vec2Int32{X: cx, Y: cy}]; taken {
					return false
				}
			}
		}
		return true
	}

	// spotNextTo: a free place for a new entity of size s touching entity (right, top, left, bottom)
	spotNextTo := func(entity Entity, s int32) (Vec2Int32, bool) {
		x, y, es := entity.Position.X, entity.Position.Y, props[entity.EntityType].Size
		for k := int32(0); k < es; k++ {
			candidates := [4]Vec2Int32{
				{X: x + es, Y: y + k}, {X: x + k, Y: y + es}, {X: x - s, Y: y + k}, {X: x + k, Y: y - s},
			}
			for _, c := range candidates {
				if free(c.X, c.Y, s) {
					return c, true
				}
			}
		}
		return Vec2Int32{}, false
	}

	// what the builders should put up next: a missing base, then a house when the population is nearly full
	var wanted []EntityType
	for _, t := range BASES_WANTED {
		if count[t] == 0 {
			wanted = append(wanted, t)
		}
	}
	housePending := false
	for _, e := range mine {
		if e.EntityType == EntityTypeHouse && !e.Active {
			housePending = true
			break
		}
	}
	if used+3 > provided && !housePending {
		wanted = append(wanted, EntityTypeHouse)
	}
	var damaged, fighters []Entity
	home, homeFound := Vec2Int32{X: size / 2, Y: size / 2}, false
	for _, e := range mine {
		p := props[e.EntityType]
		if !p.CanMove && e.Health < p.MaxHealth {
			damaged = append(damaged, e)
		}
		if p.CanMove && e.EntityType != EntityTypeBuilderUnit {
			fighters = append(fighters, e)
		}
		if !p.CanMove && !homeFound { // the first building is home; the map centre when there is none
			home, homeFound = e.Position, true
		}
	}

	// who spends first: the builder base while builders are few, the fighting bases (and houses) after that
	var builderBases, others []Entity
	for _, e := range mine {
		if e.EntityType == EntityTypeBuilderBase {
			builderBases = append(builderBases, e)
		} else {
			others = append(others, e)
		}
	}
	order := make([]Entity, 0, len(mine))
	if count[EntityTypeBuilderUnit] < FIRST_BUILDERS {
		order = append(append(order, builderBases...), others...)
	} else {
		order = append(append(order, others...), builderBases...)
	}

	result := Action{EntityActions: make(map[int32]EntityAction)}
	for _, e := range order {
		p := props[e.EntityType]
		var action EntityAction
		if e.EntityType == EntityTypeBuilderUnit {
			if target := nearest(damaged, e.Position); target != nil && distance(target.Position, e.Position) <= REPAIR_RANGE {
				// a repair needs an adjacent builder
				action.MoveAction = &MoveAction{Target: target.Position, FindClosestPosition: true, BreakThrough: false}
				action.RepairAction = &RepairAction{Target: target.Id}
			} else {
				for i, t := range wanted {
					if spot, ok := spotNextTo(e, props[t].Size); ok && resources >= props[t].InitialCost {
						action.BuildAction = &BuildAction{EntityType: t, Position: spot}
						resources -= props[t].InitialCost
						wanted = append(wanted[:i], wanted[i+1:]...)
						break
					}
				}
				if action.BuildAction == nil { // gather: the nearest resource, however far
					action.AttackAction = &AttackAction{AutoAttack: &AutoAttack{
						PathfindRange: size, ValidTargets: []EntityType{EntityTypeResource},
					}}
				}
			}
		} else if p.CanMove { // a fighting unit
			enemy := nearest(enemies, e.Position)
			if len(fighters) >= ARMY_SIZE && enemy != nil { // the army is big enough: hunt
				action.MoveAction = &MoveAction{Target: enemy.Position, FindClosestPosition: true, BreakThrough: true}
			} else { // otherwise guard the base
				action.MoveAction = &MoveAction{Target: home, FindClosestPosition: true, BreakThrough: false}
			}
			action.AttackAction = &AttackAction{AutoAttack: &AutoAttack{PathfindRange: p.SightRange}} // no filter: every target
		} else if p.Build != nil && e.Active { // a base: train its unit
			unit := p.Build.Options[0]
			cost := props[unit].InitialCost + count[unit] // a unit costs more the more you have
			spot, ok := spotNextTo(e, 1)
			enough := unit == EntityTypeBuilderUnit && count[unit] >= MAX_BUILDERS
			if ok && !enough && resources >= cost && used+props[unit].PopulationUse <= provided {
				action.BuildAction = &BuildAction{EntityType: unit, Position: spot}
				resources -= cost
				used += props[unit].PopulationUse
				count[unit]++
			}
		} else { // a turret shoots; houses and walls just stand
			action.AttackAction = &AttackAction{AutoAttack: &AutoAttack{PathfindRange: p.SightRange}}
		}
		result.EntityActions[e.Id] = action
	}
	return result
}

func (strategy MyStrategy) debugUpdate(playerView PlayerView, debugInterface DebugInterface) {
	debugInterface.Send(DebugCommandClear{})
	debugInterface.GetState()
}
