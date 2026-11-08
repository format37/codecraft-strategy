// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.

#include "MyStrategy.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <memory>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

constexpr std::array<EntityType, 2> BASES_WANTED{BUILDER_BASE, RANGED_BASE};
constexpr int FIRST_BUILDERS = 5;   // the builder base spends first until it has this many; then the fighting bases do
constexpr int MAX_BUILDERS = 12;
constexpr int ARMY_SIZE = 8;        // fighting units wait at home until there are this many of them
constexpr int REPAIR_RANGE = 6;     // a builder this close to a damaged or unfinished building goes to repair it

int distance(const Vec2Int& a, const Vec2Int& b)
{
    return std::abs(a.x - b.x) + std::abs(a.y - b.y);
}

// The entity closest to `position` (first one on a tie), or nullptr when there are none.
const Entity* nearest(const std::vector<const Entity*>& entities, const Vec2Int& position)
{
    auto it = std::min_element(entities.begin(), entities.end(), [&](const Entity* a, const Entity* b) {
        return distance(a->position, position) < distance(b->position, position);
    });
    return it == entities.end() ? nullptr : *it;
}

} // namespace

MyStrategy::MyStrategy() {}

Action MyStrategy::getAction(const PlayerView& playerView, DebugInterface* debugInterface)
{
    const int me = playerView.myId;
    const int size = playerView.mapSize;
    const auto& props = playerView.entityProperties;

    std::vector<const Entity*> mine, enemies;
    for (const Entity& e : playerView.entities) {
        if (e.playerId != nullptr) {
            (*e.playerId == me ? mine : enemies).push_back(&e);
        }
    }
    int resources = 0;
    for (const Player& p : playerView.players) {
        if (p.id == me) {
            resources = p.resource;
            break;
        }
    }

    std::unordered_map<EntityType, int> count;   // operator[] yields 0 for a type we have none of
    for (const Entity* e : mine) {
        ++count[e->entityType];
    }
    // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
    int provided = 0, used = 0;
    for (const Entity* e : mine) {
        const EntityProperties& p = props.at(e->entityType);
        if (e->active) {
            provided += p.populationProvide;
        }
        used += p.populationUse;
    }

    std::unordered_set<Vec2Int> occupied;
    for (const Entity& e : playerView.entities) {
        const int s = props.at(e.entityType).size;
        for (int dx = 0; dx < s; dx++) {
            for (int dy = 0; dy < s; dy++) {
                occupied.insert(Vec2Int(e.position.x + dx, e.position.y + dy));
            }
        }
    }

    // Can an entity of size `s` be placed with its lower-left corner at (x, y)?
    auto isFree = [&](int x, int y, int s) {
        for (int dx = 0; dx < s; dx++) {
            for (int dy = 0; dy < s; dy++) {
                const int cx = x + dx, cy = y + dy;
                if (cx < 0 || cx >= size || cy < 0 || cy >= size || occupied.count(Vec2Int(cx, cy))) {
                    return false;
                }
            }
        }
        return true;
    };

    // A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
    auto spotNextTo = [&](const Entity& entity, int s) -> std::optional<Vec2Int> {
        const int x = entity.position.x, y = entity.position.y, es = props.at(entity.entityType).size;
        for (int k = 0; k < es; k++) {
            for (const Vec2Int& c : {Vec2Int(x + es, y + k), Vec2Int(x + k, y + es), Vec2Int(x - s, y + k), Vec2Int(x + k, y - s)}) {
                if (isFree(c.x, c.y, s)) {
                    return c;
                }
            }
        }
        return std::nullopt;
    };

    auto autoAttack = [](const EntityProperties& p, std::vector<EntityType> validTargets) {
        return std::make_shared<AttackAction>(nullptr, std::make_shared<AutoAttack>(p.sightRange, std::move(validTargets)));
    };

    // what the builders should put up next: a missing base, then a house when the population is nearly full
    std::vector<EntityType> wanted;
    for (EntityType t : BASES_WANTED) {
        if (!count[t]) {
            wanted.push_back(t);
        }
    }
    const bool housePending = std::any_of(mine.begin(), mine.end(), [](const Entity* e) {
        return e->entityType == HOUSE && !e->active;
    });
    if (used + 3 > provided && !housePending) {
        wanted.push_back(HOUSE);
    }
    std::vector<const Entity*> damaged;
    for (const Entity* e : mine) {
        const EntityProperties& p = props.at(e->entityType);
        if (!p.canMove && e->health < p.maxHealth) {
            damaged.push_back(e);
        }
    }
    const auto fighters = std::count_if(mine.begin(), mine.end(), [&](const Entity* e) {
        return props.at(e->entityType).canMove && e->entityType != BUILDER_UNIT;
    });
    const auto firstBuilding = std::find_if(mine.begin(), mine.end(), [&](const Entity* e) {
        return !props.at(e->entityType).canMove;
    });
    const Vec2Int home = firstBuilding != mine.end() ? (*firstBuilding)->position : Vec2Int(size / 2, size / 2);

    // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
    std::vector<const Entity*> builderBases, others;
    for (const Entity* e : mine) {
        (e->entityType == BUILDER_BASE ? builderBases : others).push_back(e);
    }
    const bool buildersFirst = count[BUILDER_UNIT] < FIRST_BUILDERS;
    std::vector<const Entity*> order = buildersFirst ? builderBases : others;
    const auto& rest = buildersFirst ? others : builderBases;
    order.insert(order.end(), rest.begin(), rest.end());

    Action result;
    for (const Entity* entity : order) {
        const Entity& e = *entity;
        const EntityProperties& p = props.at(e.entityType);
        std::shared_ptr<MoveAction> move;
        std::shared_ptr<BuildAction> build;
        std::shared_ptr<AttackAction> attack;
        std::shared_ptr<RepairAction> repair;
        if (e.entityType == BUILDER_UNIT) {
            const Entity* target = nearest(damaged, e.position);
            if (target != nullptr && distance(target->position, e.position) <= REPAIR_RANGE) {
                move = std::make_shared<MoveAction>(target->position, true, false);   // a repair needs an adjacent builder
                repair = std::make_shared<RepairAction>(target->id);
            } else {
                for (auto t = wanted.begin(); t != wanted.end(); ++t) {
                    const EntityProperties& tp = props.at(*t);
                    const auto spot = spotNextTo(e, tp.size);
                    if (spot && resources >= tp.initialCost) {
                        build = std::make_shared<BuildAction>(*t, *spot);
                        resources -= tp.initialCost;
                        wanted.erase(t);
                        break;
                    }
                }
                if (build == nullptr) {                                     // gather: the nearest resource, however far
                    attack = std::make_shared<AttackAction>(nullptr, std::make_shared<AutoAttack>(size, std::vector<EntityType>{RESOURCE}));
                }
            }
        } else if (p.canMove) {                                             // a fighting unit
            const Entity* enemy = nearest(enemies, e.position);
            if (fighters >= ARMY_SIZE && enemy != nullptr) {                // the army is big enough: hunt
                move = std::make_shared<MoveAction>(enemy->position, true, true);
            } else {                                                        // otherwise guard the base
                move = std::make_shared<MoveAction>(home, true, false);
            }
            attack = autoAttack(p, {});
        } else if (p.build != nullptr && e.active) {                        // a base: train its unit
            const EntityType unit = p.build->options[0];
            const EntityProperties& up = props.at(unit);
            const int cost = up.initialCost + count[unit];                  // a unit costs more the more you have
            const auto spot = spotNextTo(e, 1);
            const bool enough = unit == BUILDER_UNIT && count[unit] >= MAX_BUILDERS;
            if (spot && !enough && resources >= cost && used + up.populationUse <= provided) {
                build = std::make_shared<BuildAction>(unit, *spot);
                resources -= cost;
                used += up.populationUse;
                count[unit]++;
            }
        } else {                                                            // a turret shoots; houses and walls just stand
            attack = autoAttack(p, {});
        }
        result.entityActions[e.id] = EntityAction(move, build, attack, repair);
    }
    return result;
}

void MyStrategy::debugUpdate(const PlayerView& playerView, DebugInterface& debugInterface)
{
    debugInterface.send(DebugCommand::Clear());
    debugInterface.getState();
}
