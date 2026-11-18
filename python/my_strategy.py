from model import *
import numpy as np

class MyStrategy:
    # One MyStrategy plays the whole game: anything you keep on self survives from tick to tick.
    build_order = dict()
    house_mask = None
    ranged_mask = None

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

    def vectorized_map(self, player_view):
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
        layers = 3 # entity type, owner, sight_range
        grid = np.zeros((layers, player_view.map_size, player_view.map_size), dtype=np.int8)
        for entity in (player_view.entities):
            # entity.position.x, entity.position.y, entity_map[entity.entity_type]
            props = player_view.entity_properties[entity.entity_type]
            for x in range(props.size):
                for y in range(props.size):
                    grid[0, entity.position.x+x, entity.position.y+y] = entity_map[entity.entity_type]
                    grid[1, entity.position.x+x, entity.position.y+y] = 0 if entity.entity_type==EntityType.RESOURCE else entity_map[entity.player_id]
                    grid[2, entity.position.x+x, entity.position.y+y] = player_view.entity_properties[entity.entity_type].sight_range
        return grid

    def init_placement(self, player_view):
        if self.house_mask is None:
            unit_size = player_view.entity_properties[EntityType.HOUSE].size
            self.house_mask = np.zeros([player_view.map_size, player_view.map_size], dtype=np.int8)            
            self.house_mask[unit_size:,unit_size:] = 1
            # self.house_mask[:, unit_size:] = 1
        if self.ranged_mask is None:
            unit_size = player_view.entity_properties[EntityType.RANGED_BASE].size
            self.ranged_mask = np.zeros([player_view.map_size, player_view.map_size], dtype=np.int8)            
            self.ranged_mask[:unit_size,:unit_size] = 1 # left bottom
            self.ranged_mask[unit_size:unit_size*3, unit_size:unit_size*3] = 1 # around the base
            # Invert
            self.ranged_mask = self.ranged_mask^1
            pass

    def place_finder(self, grid, size, entity_type):
            available_grid = np.array(grid[0])
            if entity_type == EntityType.HOUSE:
                available_grid += self.house_mask
            elif entity_type == EntityType.RANGED_BASE:
                available_grid += self.ranged_mask
            side = available_grid.shape[0]
            for x in range(side-size+1):
                for y in range(side-size+1):
                    snippet = available_grid[x:x + size, y:y + size]
                    if np.sum(snippet)==0:
                        return Vec2Int(x,y)
            return None

    def builders_mine_strategy(self, grid, builders):
        # 1. Crop top corner
        # 2. If resources in top corner - find nearest
        # 3. If no resources - proceed with shifting the diagonal border
        
        targets = dict()
        if len(builders)==0:
            return targets
        
        size = grid[0].shape[0]

        # Crop the top corner
        tri = 15
        suggestion = np.triu(np.ones((size, size)), k=size-tri)
        # mirror
        suggestion = np.fliplr(suggestion)
        available_grid = grid[0] * suggestion
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

        # Find nearest
        # Resource coordinates as an (R, 2) array
        res = np.argwhere(grid[0] == 8)   # shape (R, 2)
        if len(res):
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
        # No resources found. Send group diverse
        else:
            step = size//(len(builders)//2)
            aim_x, aim_y = 0, size
            for b in builders:
                targets[b.id] = Vec2Int(aim_x, aim_y)
                aim_x += step
                if aim_x>size:
                    aim_x = size
                    aim_y += step                
        return targets

    def free_spots_around(self, spot, unit_size, grid):
        spots = []
        map_size = grid[0].shape[0]
        for i in range(0,unit_size):            
            # left
            x = spot.x-1
            y = spot.y+i
            if x>=0 and y>=0 and x<map_size and y<map_size and grid[0][x][y] == 0:
                spots.append(Vec2Int(x,y))
            # right
            x = spot.x+unit_size
            y = spot.y+i
            if x>=0 and y>=0 and x<map_size and y<map_size and grid[0][x][y] == 0:
                spots.append(Vec2Int(x,y))
            # top
            x = spot.x+i
            y = spot.y+unit_size
            if x>=0 and y>=0 and x<map_size and y<map_size and grid[0][x][y] == 0:
                spots.append(Vec2Int(x,y))
            # bottom
            x = spot.x+i
            y = spot.y-1
            if x>=0 and y>=0 and x<map_size and y<map_size and grid[0][x][y] == 0:
                spots.append(Vec2Int(x,y))
        # Debug
        # for s in spots:
        #     self.draw_rectangle(s.x,s.y,s.x+1,s.y+1) 
        return spots

    def builder_action(self, result, me, mine, resources, builders, base, player_view, grid):
        house = next((e for e in mine if e.entity_type == EntityType.HOUSE), None)
        ranged_base = next((e for e in mine if e.entity_type == EntityType.RANGED_BASE), None)
        ranged_props = player_view.entity_properties[EntityType.RANGED_BASE]
        house_props = player_view.entity_properties[EntityType.HOUSE]
        

        enemy_bases = [Vec2Int(
            player_view.map_size-9,
            player_view.map_size-9
        )]

        count = {}
        for e in mine:
            count[e.entity_type] = count.get(e.entity_type, 0) + 1
        # for entity_type, n in count.items():
        #     self.log(f'{entity_type.name}: {n}')
        # if house is not None:
        #     self.log(f'house health: {house.health}/{house_props.max_health}')

        # One house
        house_spot = None
        if house is None and base is not None and resources >= house_props.initial_cost:
            if 'house' not in self.build_order.keys():
                house_spot = self.place_finder(grid, house_props.size, EntityType.HOUSE)
                self.build_order['house'] = house_spot
            else:
                house_spot = self.build_order['house']
            if house_spot is not None:
                self.draw_rectangle(house_spot.x, house_spot.y,
                    house_spot.x + house_props.size, house_spot.y + house_props.size)

        # One ranged factory
        if house is not None \
            and house.health == house_props.max_health \
            and ranged_base is None:
            if 'ranged_base' not in self.build_order.keys():
                ranged_spot = self.place_finder(grid, ranged_props.size, EntityType.RANGED_BASE)
            else:
                ranged_spot = self.build_order['ranged_base']
            if ranged_spot is not None:
                self.draw_rectangle(ranged_spot.x, ranged_spot.y,
                    ranged_spot.x + ranged_props.size, ranged_spot.y + ranged_props.size)

        # Of the actions given to an entity, the first one possible this tick is done, in the order
        # attack, build, repair, move. So "build (or repair), else move" walks a builder to the house
        # and starts the job as soon as it is next to it.
        if house_spot is not None:
            spots_around = self.free_spots_around(house_spot, house_props.size, grid)
            current_spot = 0
        elif house is not None and house.health < house_props.max_health:
            spots_around = self.free_spots_around(house.position, house_props.size, grid)
            current_spot = 0
        elif house is not None \
            and house.health == house_props.max_health \
            and ranged_base is None \
            and resources >= ranged_props.initial_cost \
            and ranged_spot is not None:
            spots_around = self.free_spots_around(ranged_spot, ranged_props.size, grid)
            current_spot = 0
        elif ranged_base is not None and ranged_base.health < ranged_props.max_health:
            spots_around = self.free_spots_around(ranged_base.position, ranged_props.size, grid)
            current_spot = 0

        for builder in builders:
            # Build home
            if house_spot is not None and len(spots_around):
                build = BuildAction(EntityType.HOUSE, house_spot)
                move_spot = spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), build, None, None)
                current_spot += 1
                if current_spot>len(spots_around)-1:
                    current_spot = 0
            # Repair home
            elif house is not None and house.health < house_props.max_health and len(spots_around):
                move_spot = spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), None, None, RepairAction(house.id))
                current_spot += 1
                if current_spot>len(spots_around)-1:
                    current_spot = 0
            # Build ranged base
            elif house is not None \
                        and house.health == house_props.max_health \
                        and ranged_base is None \
                        and resources >= ranged_props.initial_cost \
                        and ranged_spot is not None:
                if 'house' in self.build_order.keys():
                    self.build_order.pop('house')
                build = BuildAction(EntityType.RANGED_BASE, ranged_spot)
                move_spot = spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), build, None, None)
                current_spot += 1
                if current_spot>len(spots_around)-1:
                    current_spot = 0
            # Repair ranged base
            elif ranged_base is not None and ranged_base.health < ranged_props.max_health and len(spots_around):
                move_spot = spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), None, None, RepairAction(ranged_base.id))
                current_spot += 1
                if current_spot>len(spots_around)-1:
                    current_spot = 0
            # Thoughtless mining: step right. A move into an adjacent cell with a resource mines it.
            else:
                targets = self.builders_mine_strategy(grid, builders)
                # step = Vec2Int(builder.position.x + 1, builder.position.y)
                if len(targets) and builder.id in targets.keys():
                    step = targets[builder.id]
                else:
                    step = enemy_bases[0]
                result.entity_actions[builder.id] = EntityAction(MoveAction(step, True, False), None, None, None)
                # self.log(f'no targets for builder {builder.id}')

    def produce_builders(self, resources, base, population_capacity, result, player_view, builders):
        if base is None:
            return
        builder_props = player_view.entity_properties[EntityType.BUILDER_UNIT]
        if resources >= builder_props.initial_cost + len(builders) and population_capacity>3:
            new_unit_spot = Vec2Int(base.position.x+4,base.position.y-1) # ToDo: Find empty
            build = BuildAction(EntityType.BUILDER_UNIT, new_unit_spot)
            result.entity_actions[base.id] = EntityAction(None, build, None, None)
            self.draw_rectangle(new_unit_spot.x,new_unit_spot.y,new_unit_spot.x+1,new_unit_spot.y+1)
        else:
            result.entity_actions[base.id] = EntityAction(None, None, None, None)

    def produce_ranged(self, resources, base, population_capacity, result, player_view, ranged_units, grid):
        count_ranged = 0 if ranged_units is None else len(ranged_units)
        if base is None:
            return
        unit_props = player_view.entity_properties[EntityType.RANGED_UNIT]
        base_props = player_view.entity_properties[EntityType.RANGED_BASE]
        if resources >= unit_props.initial_cost + count_ranged and population_capacity>0:
            new_unit_spot = self.free_spots_around(base.position, base_props.size, grid)
            if len(new_unit_spot):
                new_unit_spot = new_unit_spot[-1]
            else:
                return
            build = BuildAction(EntityType.RANGED_UNIT, new_unit_spot)
            result.entity_actions[base.id] = EntityAction(None, build, None, None)
            self.draw_rectangle(new_unit_spot.x,new_unit_spot.y,new_unit_spot.x+1,new_unit_spot.y+1)
        else:
            result.entity_actions[base.id] = EntityAction(None, None, None, None)

    def ranged_action(self, result, ranged_units, player_view):
        if len(ranged_units) == 0:
            return
        enemy_bases = [Vec2Int(
            player_view.map_size-9,
            player_view.map_size-9
        )]
        for unit in ranged_units:
            attack = AttackAction(None, None)
            move = MoveAction(enemy_bases[0], True, True)
            result.entity_actions[unit.id] = EntityAction(move, None, attack, None)

    def get_action(self, player_view, debug_interface):
        self.init_placement(player_view)
        self.debug = debug_interface  # None on the server and in batch mode: there is no viewer to draw in
        me = player_view.my_id
        mine = [e for e in player_view.entities if e.player_id == me]
        resources = next(p.resource for p in player_view.players if p.id == me)
        builders = [e for e in mine if e.entity_type == EntityType.BUILDER_UNIT]
        base = next((e for e in mine if e.entity_type == EntityType.BUILDER_BASE), None)
        ranged_base = next((e for e in mine if e.entity_type == EntityType.RANGED_BASE), None)
        
        # ranged_units = next((e for e in mine if e.entity_type == EntityType.RANGED_UNIT), None)
        ranged_units = []
        for e in mine:
            if e.entity_type == EntityType.RANGED_UNIT:
                ranged_units.append(e)

        # population capacity
        population_provide = 0
        population_use = 0
        for e in mine:
            population_provide += player_view.entity_properties[e.entity_type].population_provide
            population_use += player_view.entity_properties[e.entity_type].population_use
        population_capacity = max(0, population_provide - population_use)

        result = Action({})

        grid = self.vectorized_map(player_view)

        self.builder_action(result, me, mine, resources, builders, base, player_view, grid)
        self.produce_builders(resources, base, population_capacity, result, player_view, builders)
        self.produce_ranged(resources, ranged_base, population_capacity, result, player_view, ranged_units, grid)
        self.ranged_action(result, ranged_units, player_view)

        return result

    def debug_update(self, player_view, debug_interface):
        # main.py calls this while the viewer waits between ticks; drawings sent here show on every tick
        pass
