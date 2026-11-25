from model import *
import numpy as np
from scipy.optimize import linear_sum_assignment

class MyStrategy:
    # build_order = dict()
    house_mask = None
    ranged_mask = None
    builders = []
    entity_map = None
    house_mask_complete = False

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
        self.entity_map = {
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
        layers = 4 # entity type, owner, sight_range, entity_id
        grid = np.zeros((layers, player_view.map_size, player_view.map_size), dtype=np.int16)
        for entity in (player_view.entities):
            props = player_view.entity_properties[entity.entity_type]
            for x in range(props.size):
                for y in range(props.size):
                    grid[0, entity.position.x+x, entity.position.y+y] = \
                        self.entity_map[entity.entity_type]
                    grid[1, entity.position.x+x, entity.position.y+y] = \
                        0 if entity.entity_type==EntityType.RESOURCE else entity.player_id
                    grid[2, entity.position.x+x, entity.position.y+y] = \
                        player_view.entity_properties[entity.entity_type].sight_range
                    grid[3, entity.position.x+x, entity.position.y+y] = \
                        entity.id

        return grid

    def init_placement(self, player_view, grid):
        # if self.house_mask is None or self.house_mask_complete == False:
        if not self.house_mask_complete:
            unit_size = player_view.entity_properties[EntityType.HOUSE].size
            self.house_mask = np.zeros([player_view.map_size, player_view.map_size], dtype=np.int8)
            self.house_mask[unit_size:,unit_size:] = 1
            # Don't build around corner until corner is not colonized
            corner = grid[0][0:3,0:3]
            corner_mask = np.argwhere(corner==8)
            if corner_mask.sum()>0:
                self.house_mask[0:3,0:6]=1
                # self.house_mask[0:6,0:3]=1
            else:
                self.house_mask_complete = True
            pass
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
        side = available_grid.shape[0]
        if entity_type == EntityType.HOUSE:
            available_grid += self.house_mask
            for x in range(0, side-size+1, size):
                snippet = available_grid[x:x + size, 0]
                if np.sum(snippet)==0:
                    return Vec2Int(x,0)
                snippet = available_grid[0, x:x + size]
                if np.sum(snippet)==0:
                    return Vec2Int(0,x)
        elif entity_type == EntityType.RANGED_BASE:
            available_grid += self.ranged_mask
            for x in range(side-size+1):
                for y in range(side-size+1):
                    snippet = available_grid[x:x + size, y:y + size]
                    if np.sum(snippet)==0:
                        return Vec2Int(x,y)
        return None

    def resource_availability_mask(self, grid):
        # Remove all resources that has no empty neighbor
        size = grid[0].shape[0]
        mask = (grid[0] == 8).astype(int)
        res = np.argwhere(grid[0] == 8)
        allowable_states = [0, 2] # empty and builder
        for r in res:
            x, y = r[0],r[1]
            available_l = x>0 and grid[0][x-1][y] in allowable_states       # Left
            available_r = x<size-1 and grid[0][x+1][y] in allowable_states    # Right            
            available_t = y<size-1 and grid[0][x][y+1] in allowable_states    # Top
            available_b = y>0 and grid[0][x][y-1] in allowable_states        # Bottom
            if not available_l and not available_r and not available_t and not available_b:
                mask[x][y] = 0
        return mask

    def builders_mine_strategy(self, grid, builders):
        # 1. find nearest
        # 2. If no resources - proceed with shifting the diagonal border
        
        targets = dict()
        if len(builders)==0:
            return targets
        
        size = grid[0].shape[0]

        # Find nearest
        # Resource coordinates as an (R, 2) array
        ra_mask = self.resource_availability_mask(grid)
        res = np.argwhere(grid[0]*ra_mask == 8)  # shape (R, 2)
        if len(res):
            b_num = 0
            bpos = np.array([(b.position.x, b.position.y) for b in builders])   # shape (B, 2), int
            dist = np.abs(bpos[:, None, :] - res[None, :, :]).sum(axis=-1)   # shape (B, R)
            rows, cols = linear_sum_assignment(dist)   # dist: (B, R), works for any shape
            target_of = dist.argmin(axis=1)
            target_of[rows] = cols
            for b in builders:
                targets[b.id] = res[target_of[b_num]]
                b_num += 1
        # No resources found. Send group diverse
        else:
            step = size // max(1, len(builders) // 2)
            aim_x, aim_y = 0, size
            for b in builders:
                targets[b.id] = (aim_x, aim_y)
                aim_x += step
                if aim_x>size:
                    aim_x = size
                    aim_y += step                
        return targets

    def free_spots_around(self, spot, unit_size, grid):
        spots = []
        if spot is None:
            return spots
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
        return spots

    def building_decision(self, entity_type, repair_order, build_order, player_view, resources_counted, grid, limit = None):
        if limit is not None:
            entity_count = len(np.argwhere(grid[0]==self.entity_map[entity_type]))
            if entity_count>=limit:
                return
        entity_props = player_view.entity_properties[entity_type]
        entity_in_order_to_repair = False
        for entity in repair_order:
            if entity.entity_type == entity_type:
                entity_in_order_to_repair = True
                break
        if resources_counted >= entity_props.initial_cost and not entity_in_order_to_repair:
            build_order.append(entity_type)
            resources_counted -= entity_props.initial_cost

    def get_build_order(self, resources, player_view, grid, repair_order, population_capacity):
        resources_counted = int(resources)
        build_order = []
        self.building_decision(EntityType.RANGED_BASE, repair_order, build_order, player_view, resources_counted, grid, 1)
        self.building_decision(EntityType.HOUSE, repair_order, build_order, player_view, resources_counted, grid)
        return build_order

    def get_repair_order(self, player_view, grid, mine):
        entities_to_repair = []
        entities = np.where(((grid[0] == 3) | (grid[0] == 4)) & (grid[1] == player_view.my_id)) # (houses or range_bases) my
        ids = grid[3][entities]
        for idx in ids:
            entity = self.get_entity(mine, idx)
            health = entity.health
            entity_props = player_view.entity_properties[entity.entity_type]
            if health<entity_props.max_health:
                entities_to_repair.append(entity)
        return entities_to_repair

    def get_entity(self, mine, entity_id):
        return next((e for e in mine if e.id == entity_id), None)

    def repair_action(self, entity, grid, builder, result, current_spot, player_view):
        entity_props = player_view.entity_properties[entity.entity_type]
        spots_around = self.free_spots_around(entity.position, entity_props.size, grid)
        if current_spot>len(spots_around)-1:
            current_spot = 0
        if len(spots_around):
            move_spot = spots_around[current_spot]
            result.entity_actions[builder.id] = EntityAction(
                MoveAction(move_spot, True, False), None, None, RepairAction(entity.id))
            current_spot += 1 # New spot for each new repair unit
            if current_spot>len(spots_around)-1:
                current_spot = 0

    def builder_action(self, result, mine, resources, builders, base, player_view, grid, population_capacity):
        house = next((e for e in mine if e.entity_type == EntityType.HOUSE), None)
        repair_order = self.get_repair_order(player_view, grid, mine)
        build_order = self.get_build_order(resources, player_view, grid, repair_order, population_capacity)
        # TODO: Don't update builder until his current task is not finished
        if len(build_order)==0 and len(repair_order)==0:
            return
        
        if len(self.builders)<2: # TODO: Fix - Buggy with 3
            for b in builders:
                self.builders.append(b)
        
        ranged_props = player_view.entity_properties[EntityType.RANGED_BASE]
        house_props = player_view.entity_properties[EntityType.HOUSE]

        # House
        house_spot = None
        if EntityType.HOUSE in build_order:
            house_spot = self.place_finder(grid, house_props.size, EntityType.HOUSE)
            house_spots_around = self.free_spots_around(house_spot, house_props.size, grid)

        # Ranged factory
        if EntityType.RANGED_BASE in build_order:
            ranged_spot = self.place_finder(grid, ranged_props.size, EntityType.RANGED_BASE)
            ranged_spots_around = self.free_spots_around(ranged_spot, ranged_props.size, grid)

        current_spot = 0 # TODO: Make special for each building

        house_in_order_to_repair = []
        ranged_in_order_to_repair = []
        for entity in repair_order:
            if entity.entity_type == EntityType.HOUSE:
                house_in_order_to_repair.append(entity)
            elif entity.entity_type == EntityType.RANGED_BASE:
                ranged_in_order_to_repair.append(entity)

        for builder in self.builders:
            
            # TODO: Concatenate build functions
            # Build house
            if EntityType.HOUSE in build_order and len(house_spots_around):
                build = BuildAction(EntityType.HOUSE, house_spot)
                move_spot = house_spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), build, None, None)
                current_spot += 1
                if current_spot>len(house_spots_around)-1:
                    current_spot = 0
            # Repair house
            if len(house_in_order_to_repair):
                entity = house_in_order_to_repair[0]
                self.repair_action(entity, grid, builder, result, current_spot, player_view)
            
            # Build ranged base
            if EntityType.RANGED_BASE in build_order and len(ranged_spots_around):
                build = BuildAction(EntityType.RANGED_BASE, ranged_spot)
                move_spot = ranged_spots_around[current_spot]
                result.entity_actions[builder.id] = EntityAction(
                    MoveAction(move_spot, True, False), build, None, None)
                current_spot += 1
                if current_spot>len(ranged_spots_around)-1:
                    current_spot = 0
            # Repair ranged base
            if len(ranged_in_order_to_repair):
                entity = ranged_in_order_to_repair[0]
                self.repair_action(entity, grid, builder, result, current_spot, player_view)
    
    def miner_action(self, result, builders, grid):
        targets = self.builders_mine_strategy(grid, builders)
        for builder in builders:
            if builder not in self.builders:
                if len(targets) and builder.id in targets.keys():
                    # step = targets[builder.id]
                    step = Vec2Int(*targets[builder.id])
                result.entity_actions[builder.id] = EntityAction(MoveAction(step, True, False), None, None, None)

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

    def ranged_action(self, result, ranged_units, player_view, grid):
        if len(ranged_units) == 0:
            return
        attack = AttackAction(None, None)
        # Find enemy
        # not res, not walls, not my
        # enemy_units = np.where((grid[0] != 8) & (grid[0] != 10) & (grid[1] != player_view.my_id))
        enemy_units = np.argwhere((grid[0] != 8) & (grid[0] != 10) & (grid[1] != player_view.my_id) & (grid[1] != 0))
        if len(enemy_units):
            # ranged position
            r_num = 0
            rpos = np.array([(r.position.x, r.position.y) for r in ranged_units])   # shape (B, 2), int
            dist = np.abs(rpos[:, None, :] - enemy_units[None, :, :]).sum(axis=-1)   # shape (B, R)
            rows, cols = linear_sum_assignment(dist)   # dist: (B, R), works for any shape
            target_of = dist.argmin(axis=1)
            target_of[rows] = cols
            for unit in ranged_units:
                target = enemy_units[target_of[r_num]]
                move = MoveAction(Vec2Int(target[0], target[1]), True, True)
                result.entity_actions[unit.id] = EntityAction(move, None, attack, None)
                r_num += 1
            return

        # Go to the base
        enemy_bases = [Vec2Int(
            player_view.map_size-9,
            player_view.map_size-9
        )]
        for unit in ranged_units:
            move = MoveAction(enemy_bases[0], True, True)
            result.entity_actions[unit.id] = EntityAction(move, None, attack, None)

    def get_action(self, player_view, debug_interface):
        self.debug = debug_interface  # None on the server and in batch mode: there is no viewer to draw in
        grid = self.vectorized_map(player_view)
        self.init_placement(player_view, grid)
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

        

        self.miner_action(result, builders, grid)
        self.builder_action(result, mine, resources, builders, base, player_view, grid, population_capacity)
        self.produce_builders(resources, base, population_capacity, result, player_view, builders)
        self.produce_ranged(resources, ranged_base, population_capacity, result, player_view, ranged_units, grid)
        self.ranged_action(result, ranged_units, player_view, grid)

        return result

    def debug_update(self, player_view, debug_interface):
        # main.py calls this while the viewer waits between ticks; drawings sent here show on every tick
        pass
