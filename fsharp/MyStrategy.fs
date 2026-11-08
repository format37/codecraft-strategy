// A starter strategy for CodeCraft 2020: builders gather resources, repair the base
// and put up houses (and the bases that Round 2 starts without) as the population fills up; the bases
// train units, builders first; the army gathers at home until it is big enough, then hunts the nearest
// enemy, shooting whatever comes into range. Rules: https://github.com/format37/codecraft/blob/master/docs/doc-en.md.
// Make it yours.
namespace Aicup2020

open Aicup2020.Model

[<AutoOpen>]
module StrategyConstants =
    let BASES_WANTED = [ EntityType.BuilderBase; EntityType.RangedBase ]
    let FIRST_BUILDERS = 5        // the builder base spends first until it has this many; then the fighting bases do
    let MAX_BUILDERS = 12
    let ARMY_SIZE = 8             // fighting units wait at home until there are this many of them
    let REPAIR_RANGE = 6          // a builder this close to a damaged or unfinished building goes to repair it

type MyStrategy() =
    member this.getAction(playerView: PlayerView, debugInterface: Option<DebugInterface>): Action =
        let me = playerView.MyId
        let size = playerView.MapSize
        let props = playerView.EntityProperties
        let mine = playerView.Entities |> Array.filter (fun e -> e.PlayerId = Some me)
        let enemies = playerView.Entities |> Array.filter (fun e -> e.PlayerId |> Option.exists (fun owner -> owner <> me))
        let mutable resources = (playerView.Players |> Array.find (fun p -> p.Id = me)).Resource

        let count = System.Collections.Generic.Dictionary<EntityType, int>()   // my entities per type
        let countOf t = match count.TryGetValue t with | true, n -> n | _ -> 0
        for e in mine do count.[e.EntityType] <- countOf e.EntityType + 1
        // population: active buildings provide it, every unit uses it (the engine refuses a unit beyond it)
        let provided = mine |> Array.sumBy (fun e -> if e.Active then props.[e.EntityType].PopulationProvide else 0)
        let mutable used = mine |> Array.sumBy (fun e -> props.[e.EntityType].PopulationUse)

        let occupied =
            set [
                for e in playerView.Entities do
                    let s = props.[e.EntityType].Size
                    for dx in 0 .. s - 1 do
                        for dy in 0 .. s - 1 do
                            yield (e.Position.X + dx, e.Position.Y + dy)
            ]

        // Can an entity of size `s` be placed with its lower-left corner at (x, y)?
        let free x y s =
            seq { for dx in 0 .. s - 1 do for dy in 0 .. s - 1 do yield (x + dx, y + dy) }
            |> Seq.forall (fun (cx, cy) -> 0 <= cx && cx < size && 0 <= cy && cy < size && not (Set.contains (cx, cy) occupied))

        // A free place for a new entity of size `s` touching `entity` (right, top, left, bottom).
        let spotNextTo (entity: Entity) s =
            let x, y, es = entity.Position.X, entity.Position.Y, props.[entity.EntityType].Size
            seq {
                for k in 0 .. es - 1 do
                    yield (x + es, y + k)
                    yield (x + k, y + es)
                    yield (x - s, y + k)
                    yield (x + k, y - s)
            }
            |> Seq.tryFind (fun (cx, cy) -> free cx cy s)
            |> Option.map (fun (cx, cy) -> { Vec2Int.X = cx; Y = cy })

        let distance (a: Vec2Int) (b: Vec2Int) = abs (a.X - b.X) + abs (a.Y - b.Y)

        let nearest (entities: Entity[]) position =
            if Array.isEmpty entities then None
            else Some (entities |> Array.minBy (fun e -> distance e.Position position))

        // an attack order with no fixed target: shoot whatever of the given kinds (none = anything) comes within `range`
        let autoAttack range targets =
            let auto = { AutoAttack.PathfindRange = range; ValidTargets = targets }
            { AttackAction.Target = None; AutoAttack = Some auto }

        // what the builders should put up next: a missing base, then a house when the population is nearly full
        let wanted = ResizeArray<EntityType>(BASES_WANTED |> List.filter (fun t -> countOf t = 0))
        let housePending = mine |> Array.exists (fun e -> e.EntityType = EntityType.House && not e.Active)
        if used + 3 > provided && not housePending then wanted.Add(EntityType.House)
        let damaged =
            mine |> Array.filter (fun e -> not props.[e.EntityType].CanMove && e.Health < props.[e.EntityType].MaxHealth)
        let fighters = mine |> Array.filter (fun e -> props.[e.EntityType].CanMove && e.EntityType <> EntityType.BuilderUnit)
        let home =
            mine
            |> Array.tryFind (fun e -> not props.[e.EntityType].CanMove)
            |> Option.map (fun e -> e.Position)
            |> Option.defaultValue { Vec2Int.X = size / 2; Y = size / 2 }

        // who spends first: the builder base while builders are few, the fighting bases (and houses) after that
        let builderBases, others = mine |> Array.partition (fun e -> e.EntityType = EntityType.BuilderBase)
        let order =
            if countOf EntityType.BuilderUnit < FIRST_BUILDERS then Array.append builderBases others
            else Array.append others builderBases

        // among attack, build, repair and move the engine performs only the first one possible each tick,
        // so a builder that is told to build or repair gets no attack order
        let mutable result: Map<int, EntityAction> = Map.empty
        for e in order do
            let p = props.[e.EntityType]
            let mutable move: MoveAction option = None
            let mutable build: BuildAction option = None
            let mutable attack: AttackAction option = None
            let mutable repair: RepairAction option = None
            if e.EntityType = EntityType.BuilderUnit then
                match nearest damaged e.Position with
                | Some target when distance target.Position e.Position <= REPAIR_RANGE ->
                    // a repair needs an adjacent builder
                    move <- Some { MoveAction.Target = target.Position; FindClosestPosition = true; BreakThrough = false }
                    repair <- Some { RepairAction.Target = target.Id }
                | _ ->
                    // the first wanted building that fits next to the builder and is affordable
                    let mutable i = 0
                    while Option.isNone build && i < wanted.Count do
                        let t = wanted.[i]
                        match spotNextTo e props.[t].Size with
                        | Some spot when resources >= props.[t].InitialCost ->
                            build <- Some { BuildAction.EntityType = t; Position = spot }
                            resources <- resources - props.[t].InitialCost
                            wanted.RemoveAt(i)
                        | _ -> i <- i + 1
                    if Option.isNone build then                            // gather: the nearest resource, however far
                        attack <- Some (autoAttack size [| EntityType.Resource |])
            elif p.CanMove then                                            // a fighting unit
                move <-
                    match nearest enemies e.Position with
                    | Some enemy when fighters.Length >= ARMY_SIZE ->      // the army is big enough: hunt
                        Some { MoveAction.Target = enemy.Position; FindClosestPosition = true; BreakThrough = true }
                    | _ ->                                                 // otherwise guard the base
                        Some { MoveAction.Target = home; FindClosestPosition = true; BreakThrough = false }
                attack <- Some (autoAttack p.SightRange [||])
            else
                match p.Build with
                | Some b when e.Active ->                                  // a base: train its unit
                    let unitType = b.Options.[0]
                    let cost = props.[unitType].InitialCost + countOf unitType   // a unit costs more the more you have
                    let enough = (unitType = EntityType.BuilderUnit) && countOf unitType >= MAX_BUILDERS
                    match spotNextTo e 1 with
                    | Some spot when not enough && resources >= cost && used + props.[unitType].PopulationUse <= provided ->
                        build <- Some { BuildAction.EntityType = unitType; Position = spot }
                        resources <- resources - cost
                        used <- used + props.[unitType].PopulationUse
                        count.[unitType] <- countOf unitType + 1
                    | _ -> ()
                | _ ->                                                     // a turret shoots; houses and walls just stand
                    attack <- Some (autoAttack p.SightRange [||])
            let action = { EntityAction.MoveAction = move; BuildAction = build; AttackAction = attack; RepairAction = repair }
            result <- Map.add e.Id action result
        { EntityActions = result }

    member this.debugUpdate(playerView: PlayerView, debugInterface: DebugInterface) =
        debugInterface.send (DebugCommand.Clear(new DebugCommandClear()))
        debugInterface.getState () |> ignore
