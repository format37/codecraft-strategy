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

    def builders_mine_strategy(self, grid, builders):
        # 1. Crop top corner
        # 2. If resources in top corner - find nearest
        # 3. If no resources - proceed with shifting the diagonal border
        
        targets = dict()
        size = grid.shape[0]

        # Crop the top corner
        tri = 15
        suggestion = np.triu(np.ones((size, size)), k=size-tri)
        # mirror
        suggestion = np.fliplr(suggestion)
        available_grid = grid * suggestion
        # Counting EntityType.RESOURCE:8
        # resources = np.where(available_grid==8)
        mask = available_grid == 8      # bool array, same shape as the grid
        only_res = available_grid * mask  # zeros everywhere except the 8s
        if only_res.sum()>0:
            # find nearest
            # Resource coordinates as an (R, 2) array
            res = np.argwhere(available_grid == 8)   # shape (R, 2)
            b_num = 0
            for b in builders:
                # Builder positions as a (B, 2) array
                bpos = np.array([(b.position.x, b.position.y) for b in builders])   # shape (B, 2), int
                # Broadcasting does the rest
                dist = np.abs(bpos[:, None, :] - res[None, :, :]).sum(axis=-1)   # shape (B, R)
                idx = dist.argmin(axis=1)   # shape (B,): nearest resource index for each builder
                target = res[idx]          # shape (B, 2): coordinates of that resource
                targets[b.id] = Vec2Int(target[b_num][0], target[b_num][1])
                b_num += 1
        if len(targets):
            return targets

        resources = []
        if only_res.sum()==0:
            # Proceed from the grid tip
            for tri in range(1-size,size,1):
                # k = -tri is diagonal bias
                suggestion = np.triu(np.ones((size, size)), k=-tri)
                # mirror
                suggestion = np.fliplr(suggestion)
                # builder_grid = grid * suggestion
                # Counting EntityType.RESOURCE:8
                # resources = np.where(builder_grid==8)
                mask = available_grid == 8      # bool array, same shape as the grid
                only_res = available_grid * mask  # zeros everywhere except the 8s
                if only_res.sum():
                    break

        if only_res.sum()>0:
            return targets
        # r = 0
        # for b in builders:
        #     targets[b.id] = Vec2Int(only_res[0], only_res[1])
        #     # Next builder, next resource
        #     r += 1
        #     if r>=len(resources):
        #         r = 0
        # find nearest
        # Resource coordinates as an (R, 2) array
        res = np.argwhere(grid == 8)   # shape (R, 2)
        b_num = 0
        for b in builders:
            # Builder positions as a (B, 2) array
            bpos = np.array([(b.position.x, b.position.y) for b in builders])   # shape (B, 2), int
            # Broadcasting does the rest
            dist = np.abs(bpos[:, None, :] - res[None, :, :]).sum(axis=-1)   # shape (B, R)
            idx = dist.argmin(axis=1)   # shape (B,): nearest resource index for each builder
            target = res[idx]          # shape (B, 2): coordinates of that resource
            targets[b.id] = Vec2Int(target[b_num][0], target[b_num][1])
            b_num += 1
                
        return targets

    def builder_action(self, result, me, mine, resources, builders, base, player_view):
        house = next((e for e in mine if e.entity_type == EntityType.HOUSE), None)
        ranged_base = next((e for e in mine if e.entity_type == EntityType.RANGED_BASE), None)
        ranged_props = player_view.entity_properties[EntityType.RANGED_BASE]
        house_props = player_view.entity_properties[EntityType.HOUSE]
        

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
                if 'house' in self.build_order.keys():
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
                targets = self.builders_mine_strategy(grid, builders)
                # step = Vec2Int(builder.position.x + 1, builder.position.y)
                if len(targets) and builder.id in targets.keys():
                    step = targets[builder.id]
                else:
                    step = enemy_bases[0]
                result.entity_actions[builder.id] = EntityAction(MoveAction(step, True, False), None, None, None)
                self.log(f'no targets for builder {builder.id}')

    def produce_builders(self, resources, base, population_capacity, result, player_view):
        builder_props = player_view.entity_properties[EntityType.BUILDER_UNIT]
        if resources >= builder_props.initial_cost and population_capacity>0:
            new_unit_spot = Vec2Int(base.position.x+4,base.position.y-1) # ToDo: Find empty
            build = BuildAction(EntityType.BUILDER_UNIT, new_unit_spot)
            result.entity_actions[base.id] = EntityAction(None, build, None, None)
            self.draw_rectangle(new_unit_spot.x,new_unit_spot.y,new_unit_spot.x+1,new_unit_spot.y+1)

    def get_action(self, player_view, debug_interface):
        self.debug = debug_interface  # None on the server and in batch mode: there is no viewer to draw in
        me = player_view.my_id
        mine = [e for e in player_view.entities if e.player_id == me]
        resources = next(p.resource for p in player_view.players if p.id == me)
        builders = [e for e in mine if e.entity_type == EntityType.BUILDER_UNIT]
        base = next((e for e in mine if e.entity_type == EntityType.BUILDER_BASE), None)

        # population capacity
        population_provide = 0
        population_use = 0
        for e in mine:
            population_provide += player_view.entity_properties[e.entity_type].population_provide
            population_use += player_view.entity_properties[e.entity_type].population_use
        population_capacity = max(0, population_provide - population_use)

        result = Action({})

        self.builder_action(result, me, mine, resources, builders, base, player_view)
        self.produce_builders(resources, base, population_capacity, result, player_view)

        return result

    def debug_update(self, player_view, debug_interface):
        # main.py calls this while the viewer waits between ticks; drawings sent here show on every tick
        pass
