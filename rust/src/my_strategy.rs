use super::DebugInterface;
use model::*;
use std::collections::{HashMap, HashSet};

// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

const BASES_WANTED: [EntityType; 2] = [EntityType::BuilderBase, EntityType::RangedBase];
const FIRST_BUILDERS: i32 = 5; // the builder base spends first until it has this many; then the fighting bases do
const MAX_BUILDERS: i32 = 12;
const ARMY_SIZE: usize = 8; // fighting units wait at home until there are this many of them
const REPAIR_RANGE: i32 = 6; // a builder this close to a damaged or unfinished building goes to repair it

pub struct MyStrategy {}

impl MyStrategy {
    pub fn new() -> Self {
        Self {}
    }
    pub fn get_action(
        &mut self,
        player_view: &PlayerView,
        _debug_interface: Option<&mut DebugInterface>,
    ) -> Action {
        let me = player_view.my_id;
        let size = player_view.map_size;
        let props = &player_view.entity_properties;
        let mine: Vec<&Entity> = player_view
            .entities
            .iter()
            .filter(|e| e.player_id == Some(me))
            .collect();
        let enemies: Vec<&Entity> = player_view
            .entities
            .iter()
            .filter(|e| e.player_id.is_some() && e.player_id != Some(me))
            .collect();
        let mut resources = player_view
            .players
            .iter()
            .find(|p| p.id == me)
            .map(|p| p.resource)
            .expect("my player is missing from the players list");

        let mut count: HashMap<EntityType, i32> = HashMap::new();
        for e in &mine {
            *count.entry(e.entity_type.clone()).or_insert(0) += 1;
        }
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        let provided: i32 = mine
            .iter()
            .filter(|e| e.active)
            .map(|e| props[&e.entity_type].population_provide)
            .sum();
        let mut used: i32 = mine
            .iter()
            .map(|e| props[&e.entity_type].population_use)
            .sum();

        let mut occupied: HashSet<(i32, i32)> = HashSet::new();
        for e in &player_view.entities {
            let s = props[&e.entity_type].size;
            for dx in 0..s {
                for dy in 0..s {
                    occupied.insert((e.position.x + dx, e.position.y + dy));
                }
            }
        }

        // Can an entity of size `s` be placed with its lower-left corner at (x, y)?
        let free = |x: i32, y: i32, s: i32| -> bool {
            (0..s).all(|dx| {
                (0..s).all(|dy| {
                    let (cx, cy) = (x + dx, y + dy);
                    0 <= cx && cx < size && 0 <= cy && cy < size && !occupied.contains(&(cx, cy))
                })
            })
        };

        // A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
        let spot_next_to = |entity: &Entity, s: i32| -> Option<Vec2I32> {
            let (x, y, es) = (
                entity.position.x,
                entity.position.y,
                props[&entity.entity_type].size,
            );
            for k in 0..es {
                let candidates = [(x + es, y + k), (x + k, y + es), (x - s, y + k), (x + k, y - s)];
                for &(cx, cy) in candidates.iter() {
                    if free(cx, cy, s) {
                        return Some(Vec2I32 { x: cx, y: cy });
                    }
                }
            }
            None
        };

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        let mut wanted: Vec<EntityType> = BASES_WANTED
            .iter()
            .filter(|t| count.get(*t).copied().unwrap_or(0) == 0)
            .cloned()
            .collect();
        let house_pending = mine
            .iter()
            .any(|e| e.entity_type == EntityType::House && !e.active);
        if used + 3 > provided && !house_pending {
            wanted.push(EntityType::House);
        }
        let damaged: Vec<&Entity> = mine
            .iter()
            .copied()
            .filter(|e| {
                let p = &props[&e.entity_type];
                !p.can_move && e.health < p.max_health
            })
            .collect();
        let fighters: Vec<&Entity> = mine
            .iter()
            .copied()
            .filter(|e| props[&e.entity_type].can_move && e.entity_type != EntityType::BuilderUnit)
            .collect();
        let home = mine
            .iter()
            .find(|e| !props[&e.entity_type].can_move)
            .map(|e| e.position.clone())
            .unwrap_or(Vec2I32 {
                x: size / 2,
                y: size / 2,
            });

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        let builder_bases = mine
            .iter()
            .copied()
            .filter(|e| e.entity_type == EntityType::BuilderBase);
        let others = mine
            .iter()
            .copied()
            .filter(|e| e.entity_type != EntityType::BuilderBase);
        let order: Vec<&Entity> =
            if count.get(&EntityType::BuilderUnit).copied().unwrap_or(0) < FIRST_BUILDERS {
                builder_bases.chain(others).collect()
            } else {
                others.chain(builder_bases).collect()
            };

        let mut result = Action {
            entity_actions: HashMap::new(),
        };
        for &e in &order {
            let p = &props[&e.entity_type];
            let mut move_action: Option<MoveAction> = None;
            let mut build_action: Option<BuildAction> = None;
            let mut attack_action: Option<AttackAction> = None;
            let mut repair_action: Option<RepairAction> = None;
            if e.entity_type == EntityType::BuilderUnit {
                let target = nearest(&damaged, &e.position)
                    .filter(|t| distance(&t.position, &e.position) <= REPAIR_RANGE);
                if let Some(target) = target {
                    move_action = Some(MoveAction {
                        target: target.position.clone(), // a repair needs an adjacent builder
                        find_closest_position: true,
                        break_through: false,
                    });
                    repair_action = Some(RepairAction { target: target.id });
                } else {
                    let mut chosen = None;
                    for (i, t) in wanted.iter().enumerate() {
                        let spot = spot_next_to(e, props[t].size);
                        if let Some(spot) = spot {
                            if resources >= props[t].initial_cost {
                                chosen = Some((i, spot));
                                break;
                            }
                        }
                    }
                    if let Some((i, spot)) = chosen {
                        let t = wanted.remove(i);
                        resources -= props[&t].initial_cost;
                        build_action = Some(BuildAction {
                            entity_type: t,
                            position: spot,
                        });
                    }
                    if build_action.is_none() {
                        // gather: the nearest resource, however far
                        attack_action = Some(AttackAction {
                            target: None,
                            auto_attack: Some(AutoAttack {
                                pathfind_range: size,
                                valid_targets: vec![EntityType::Resource],
                            }),
                        });
                    }
                }
            } else if p.can_move {
                // a fighting unit
                let enemy = nearest(&enemies, &e.position);
                move_action = Some(match enemy {
                    // the army is big enough: hunt
                    Some(enemy) if fighters.len() >= ARMY_SIZE => MoveAction {
                        target: enemy.position.clone(),
                        find_closest_position: true,
                        break_through: true,
                    },
                    // otherwise guard the base
                    _ => MoveAction {
                        target: home.clone(),
                        find_closest_position: true,
                        break_through: false,
                    },
                });
                attack_action = Some(AttackAction {
                    target: None,
                    auto_attack: Some(AutoAttack {
                        pathfind_range: p.sight_range,
                        valid_targets: vec![],
                    }),
                });
            } else if let Some(bp) = p.build.as_ref().filter(|_| e.active) {
                // a base: train its unit
                let unit = &bp.options[0];
                let up = &props[unit];
                let have = count.get(unit).copied().unwrap_or(0);
                let cost = up.initial_cost + have; // a unit costs more the more you have
                let spot = spot_next_to(e, 1);
                let enough = *unit == EntityType::BuilderUnit && have >= MAX_BUILDERS;
                if let Some(spot) = spot {
                    if !enough && resources >= cost && used + up.population_use <= provided {
                        build_action = Some(BuildAction {
                            entity_type: unit.clone(),
                            position: spot,
                        });
                        resources -= cost;
                        used += up.population_use;
                        *count.entry(unit.clone()).or_insert(0) += 1;
                    }
                }
            } else {
                // a turret shoots; houses and walls just stand
                attack_action = Some(AttackAction {
                    target: None,
                    auto_attack: Some(AutoAttack {
                        pathfind_range: p.sight_range,
                        valid_targets: vec![],
                    }),
                });
            }
            result.entity_actions.insert(
                e.id,
                EntityAction {
                    move_action,
                    build_action,
                    attack_action,
                    repair_action,
                },
            );
        }
        result
    }
    pub fn debug_update(&mut self, player_view: &PlayerView, debug_interface: &mut DebugInterface) {
        debug_interface.send(DebugCommand::Clear {});
        debug_interface.get_state();
    }
}

fn distance(a: &Vec2I32, b: &Vec2I32) -> i32 {
    (a.x - b.x).abs() + (a.y - b.y).abs()
}

// The entity closest to `position` (Manhattan distance); the first one on a tie, like Python's min().
fn nearest<'a>(entities: &[&'a Entity], position: &Vec2I32) -> Option<&'a Entity> {
    entities
        .iter()
        .copied()
        .min_by_key(|e| distance(&e.position, position))
}
