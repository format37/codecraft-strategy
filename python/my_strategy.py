from model import *

class MyStrategy:
    # A place to store values between ticks
    debug = None
    
    def log(self, text):
        data = DebugData.Log(text)
        self.debug.send(DebugCommand.Add(data))

    def draw_rectangle(self, x0,y0,x1,y1, color = Color(1, 0, 0, 1)):
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]        
        vertices = []
        for i in range(4):
            for cx, cy in (corners[i], corners[(i + 1) % 4]):
                vertices.append(
                    ColoredVertex(Vec2Float(cx, cy), Vec2Float(0, 0), color)
                    )
        self.debug.send(
            DebugCommand.Add(
                DebugData.Primitives(vertices, PrimitiveType.LINES)
                )
            )

    def get_action(self, player_view, debug_interface):
        self.debug = debug_interface
        my_house = None
        build_mark_sent = False
        me = player_view.my_id
        size = player_view.map_size
        props = player_view.entity_properties
        mine = [e for e in player_view.entities if e.player_id == me]
        enemies = [e for e in player_view.entities if e.player_id is not None and e.player_id != me]
        resources = next(p.resource for p in player_view.players if p.id == me)
        count = {}
        for e in mine:
            count[e.entity_type] = count.get(e.entity_type, 0) + 1
            if e.entity_type == EntityType.HOUSE:
                my_house = e
                self.log(f'house health: {my_house.health}')

        for key, val in count.items():
            self.log(f'{key.name}: {val}')

        builder_bases = [e for e in mine if e.entity_type == EntityType.BUILDER_BASE]
        others = [e for e in mine if e.entity_type != EntityType.BUILDER_BASE]

        result = Action({})
        
        build, attack, repair = None, None, None

        for e in others:
            if e.entity_type == EntityType.BUILDER_UNIT:
                
                # Set house
                if resources >= props[EntityType.HOUSE].initial_cost and my_house is None:
                    house = EntityType.HOUSE
                    builder_base_position = builder_bases[0].position
                    house_position = Vec2Int(builder_base_position.x+5, builder_base_position.y+4)
                    build = BuildAction(house, house_position)
                    move = MoveAction(house_position, True, False)
                    result.entity_actions[e.id] = EntityAction(move, build, attack, repair)

                    if not build_mark_sent:
                        self.draw_rectangle(
                            house_position.x, 
                            house_position.y, 
                            house_position.x + props[EntityType.HOUSE].size, 
                            house_position.y + props[EntityType.HOUSE].size
                            )
                        build_mark_sent = True
                
                # Repair house
                elif my_house is not None and my_house.health < props[EntityType.HOUSE].max_health:
                    self.log(f'Need to repair house: {my_house.health}/{props[EntityType.HOUSE].max_health}')
                    repair = RepairAction(my_house.id)
                    result.entity_actions[e.id] = EntityAction(None, None, None, repair)
                    pass

                # Thoughtless mine to the right
                else: 
                    target = Vec2Int(e.position.x + 1, e.position.y)
                    move = MoveAction(target, True, False)
                    result.entity_actions[e.id] = EntityAction(move, build, attack, repair)
                
        return result

    def debug_update(self, player_view, debug_interface):
        debug_interface.send(DebugCommand.Clear())
        debug_interface.get_state()
