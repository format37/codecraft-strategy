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
            for b in builders:
                # Builder positions as a (B, 2) array
                # bpos = np.array([b.position for b in builders])   # shape (B, 2)
                bpos = np.array([(b.position.x, b.position.y) for b in builders])   # shape (B, 2), int
                # Broadcasting does the rest
                dist = np.abs(bpos[:, None, :] - res[None, :, :]).sum(axis=-1)   # shape (B, R)
                idx = dist.argmin(axis=1)   # shape (B,): nearest resource index for each builder
                target = res[idx]          # shape (B, 2): coordinates of that resource
                targets[b.id] = Vec2Int(target[0][0], target[0][1])
                pass
        if len(targets):
            return targets
            # r = 0
            # for b in builders:
            #     pos_x = b.position[0]
            #     pos_y = b.position[1]
            #     targets[b.id] = Vec2Int(resources[0][r], resources[1][r])
            #     # Next builder, next resource
            #     r += 1
            #     if r>=len(resources):
            #         r = 0
            

        # # Start from the middle of the base
        # for tri in range(15,1,-1):
        #     # k = -tri is diagonal bias
        #     # suggestion = np.triu(np.ones((size, size)), k=-tri)
        #     suggestion = np.triu(np.ones((size, size)), k=size-tri)
        #     # mirror
        #     suggestion = np.fliplr(suggestion)
        #     builder_grid = grid * suggestion
        #     # Counting EntityType.RESOURCE:8
        #     resources = np.where(builder_grid==8)
        #     if len(resources[0]):
        #         break

        if len(resources[0])==0:
            # Proceed from the grid tip
            for tri in range(1-size,size,1):
                # k = -tri is diagonal bias
                suggestion = np.triu(np.ones((size, size)), k=-tri)
                # mirror
                suggestion = np.fliplr(suggestion)
                builder_grid = grid * suggestion
                # Counting EntityType.RESOURCE:8
                resources = np.where(builder_grid==8)
                if len(resources[0]):
                    break

        if len(resources[0])==0:
            return targets
        r = 0
        for b in builders:
            targets[b.id] = Vec2Int(resources[0][r], resources[1][r])
            # Next builder, next resource
            r += 1
            if r>=len(resources):
                r = 0
                
        return targets


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

        return result

    def debug_update(self, player_view, debug_interface):
        # main.py calls this while the viewer waits between ticks; drawings sent here show on every tick
        pass
