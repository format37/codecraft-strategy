from model import *
import numpy as np

class MyStrategy:
    # One MyStrategy plays the whole game: anything you keep on self survives from tick to tick.
    build_order = dict()

    def log(self, text):
        if self.debug:
            self.debug.send(DebugCommand.Add(DebugData.Log(text)))

    def draw_rectangle(self, x0, y0, x1, y1, color=Color(1, 0, 0, 1)):
        if not self.debug:
            return
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        vertices = []
        for i in range(4):  # LINES takes vertices in pairs: one pair per side
            for x, y in (corners[i], corners[(i + 1) % 4]):
                vertices.append(ColoredVertex(Vec2Float(x, y), Vec2Float(0, 0), color))
        self.debug.send(DebugCommand.Add(DebugData.Primitives(vertices, PrimitiveType.LINES)))

    def numpymap(self, player_view):
        entity_map = {
            EntityType.BUILDER_BASE:1,
            EntityType.BUILDER_UNIT:2,
            EntityType.HOUSE:3,
            EntityType.RANGED_BASE:4,
            EntityType.RANGED_UNIT:5,
            EntityType.MELEE_BASE:6,
            EntityType.MELEE_UNIT:7,
            EntityType.RESOURCE:8,
            EntityType.TURRET:9,
            EntityType.WALL:10
        }
        # ToDo: Account entity_properties[entity.entity_type].sight_range
        grid = np.zeros((player_view.map_size, player_view.map_size), dtype=np.int8)
        for entity in (player_view.entities):
            # entity.position.x, entity.position.y, entity_map[entity.entity_type]
            props = player_view.entity_properties[entity.entity_type]
            for x in range(props.size):
                for y in range(props.size):
                    grid[entity.position.x+x, entity.position.y+y] = entity_map[entity.entity_type]
        return grid

    def place_finder(self, grid, size):
        start_point = [0,0] # ToDo: depends on current pos, don't account moving units
        side = grid.shape[0]
        for x in range(side-size+1):
            for y in range(side-size+1):
                snippet = grid[x:x + size, y:y + size]
                if np.sum(snippet)==0:
                    return Vec2Int(x,y)
        return Vec2Int(0,0)

    def get_action(self, player_view, debug_interface):
        self.debug = debug_interface  # None on the server and in batch mode: there is no viewer to draw in
        me = player_view.my_id
        house_props = player_view.entity_properties[EntityType.HOUSE]
        resources = next(p.resource for p in player_view.players if p.id == me)
        mine = [e for e in player_view.entities if e.player_id == me]
        builders = [e for e in mine if e.entity_type == EntityType.BUILDER_UNIT]
        base = next((e for e in mine if e.entity_type == EntityType.BUILDER_BASE), None)
        house = next((e for e in mine if e.entity_type == EntityType.HOUSE), None)
        ranged_base = next((e for e in mine if e.entity_type == EntityType.RANGED_BASE), None)
        ranged_props = player_view.entity_properties[EntityType.RANGED_BASE]

        enemy_bases = [Vec2Int(
            player_view.map_size-9,
            player_view.map_size-9
        )]

        grid = self.numpymap(player_view)

        count = {}
        for e in mine:
            count[e.entity_type] = count.get(e.entity_type, 0) + 1
        for entity_type, n in count.items():
            self.log(f'{entity_type.name}: {n}')
        if house is not None:
            self.log(f'house health: {house.health}/{house_props.max_health}')

        # One house
        house_spot = None
        if house is None and base is not None and resources >= house_props.initial_cost:
            if 'house' not in self.build_order.keys():
                house_spot = self.place_finder(grid, house_props.size)
                self.build_order['house'] = house_spot
            else:
                house_spot = self.build_order['house']
            self.draw_rectangle(house_spot.x, house_spot.y,
                                house_spot.x + house_props.size, house_spot.y + house_props.size)

        # One ranged factory
        if house is not None \
            and house.health == house_props.max_health \
            and ranged_base is None:
            if 'ranged_base' not in self.build_order.keys():
                ranged_spot = self.place_finder(grid, ranged_props.size)
            else:
                ranged_spot = self.build_order['ranged_base']
            self.draw_rectangle(ranged_spot.x, ranged_spot.y,
                                            ranged_spot.x + ranged_props.size, ranged_spot.y + ranged_props.size)

        # Of the actions given to an entity, the first one possible this tick is done, in the order
        # attack, build, repair, move. So "build (or repair), else move" walks a builder to the house
        # and starts the job as soon as it is next to it.
        result = Action({})
        for builder in builders:
            # Build home
            if house_spot is not None:
                build = BuildAction(EntityType.HOUSE, house_spot)
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(house_spot, True, False), build, None, None)
            # Repair home
            elif house is not None and house.health < house_props.max_health:
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(house.position, True, False), None, None, RepairAction(house.id))
            # Build ranged base
            elif house is not None \
                        and house.health == house_props.max_health \
                        and ranged_base is None \
                        and resources >= ranged_props.initial_cost:
                self.build_order.pop('house')
                build = BuildAction(EntityType.RANGED_BASE, ranged_spot)
                move_spot = Vec2Int(ranged_spot.x,ranged_spot.y)
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), build, None, None)
            # Repair ranged base
            elif ranged_base is not None and ranged_base.health < ranged_props.max_health:
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(ranged_base.position, True, False), None, None, RepairAction(ranged_base.id))
            # Thoughtless mining: step right. A move into an adjacent cell with a resource mines it.
            else:
                step = Vec2Int(builder.position.x + 1, builder.position.y)
                result.entity_actions[builder.id] = EntityAction(MoveAction(step, True, False), None, None, None)

        return result

    def debug_update(self, player_view, debug_interface):
        # main.py calls this while the viewer waits between ticks; drawings sent here show on every tick
        pass
