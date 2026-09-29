"""VRPTW, reference greedy algorithm and independent plan invariants.

All time values are integer minutes on dataset.date, Europe/Moscow.
Open routes: end nodes are artificial sinks with zero return travel.
"""

import copy
import time
import uuid

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .importer import SKILL_LABELS, TRANSPORT_LABELS, is_emergency
from .models import Dataset, Location
from .routing import Matrix


def priority_level(job):
    """Prioritize HD accidents and explicit dispatcher urgency over other work."""
    if is_emergency(job.work_type) or job.priority == "urgent":
        return 2
    if job.bk_type == "Подключение" or "подключ" in job.work_type.lower():
        return 1
    return 0


def requirements(job, settings):
    extra = []
    if settings.equipment_enabled:
        extra = settings.equipment_by_work_type.get(
            job.work_type,
            settings.equipment_by_work_type.get(job.bk_type, []),
        )
    return set(job.required_equipment) | set(extra)


def eligible(job, engineer, settings):
    reasons = []
    if not job.service_area or not engineer.service_area:
        reasons.append("Не указан участок заявки или инженера")
    elif job.service_area.casefold() != engineer.service_area.casefold():
        reasons.append(f"Другой участок: заявка - {job.service_area}, инженер - {engineer.service_area}")
    if job.required_skill not in engineer.skills:
        reasons.append("Нет нужного навыка: " + SKILL_LABELS[job.required_skill])
    if job.required_transport and job.required_transport != engineer.transport:
        reasons.append("Нужен транспорт: " + TRANSPORT_LABELS[job.required_transport])
    missing = requirements(job, settings) - set(engineer.equipment)
    if missing:
        reasons.append("Нет оборудования: " + ", ".join(sorted(missing)))
    if not engineer.available:
        reasons.append("Инженер недоступен")
    return reasons


def initial_states(ds):
    return {
        e.id: {"location": e.start_location.model_dump(), "time": e.shift_start, "stops": [], "legs": []}
        for e in ds.engineers
    }


def working_engineers(plan):
    """Keep the day roster even if an engineer's remaining jobs are cancelled."""
    if "working_engineer_ids" in plan:
        return set(plan["working_engineer_ids"])
    # Old saved plans have no roster. Start from their existing work, not all profiles.
    return {route["engineer_id"] for route in plan["routes"] if route["stops"] or route["legs"]}


class Context:
    def __init__(self, ds, storage=None, states=None, locks=None, working_engineer_ids=None):
        self.ds = ds
        self.states = states or initial_states(ds)
        self.locks = locks or {}
        self.working_engineer_ids = working_engineer_ids
        self.frozen_ids = {stop["job_id"] for state in self.states.values() for stop in state["stops"]}
        self.jobs = [j for j in ds.jobs if j.id not in self.frozen_ids]
        self.job_index = {j.id: i for i, j in enumerate(self.jobs)}
        self.engineers = ds.engineers
        locations = [j.location for j in self.jobs] + [
            Location(**self.states[e.id]["location"]) for e in self.engineers
        ]
        self.matrix = Matrix(locations, ds.settings, storage)
        self.offset = len(self.jobs)

    def assignment_reasons(self, job, engineer):
        reasons = eligible(job, engineer, self.ds.settings)
        if self.working_engineer_ids is not None and engineer.id not in self.working_engineer_ids:
            reasons.append(
                "Инженер не задействован в первоначальном плане дня; нужен явный вызов диспетчером"
            )
        if self.locks.get(job.id, {}).get("engineer_id", engineer.id) != engineer.id:
            reasons.append("Заявка зафиксирована за другим инженером")
        return reasons

    def can_assign(self, job, engineer):
        return not self.assignment_reasons(job, engineer)

    def schedule(self, vehicle, order, explain=False):
        engineer = self.engineers[vehicle]
        state = self.states[engineer.id]
        cursor = max(state["time"], engineer.shift_start)
        end_shift = min(
            engineer.shift_end, engineer.unavailable_from if engineer.unavailable_from is not None else 1440
        )
        origin_index = self.offset + vehicle
        origin = state["location"]
        stops, legs = [], []
        for idx in order:
            job = self.jobs[idx]
            if not self.can_assign(job, engineer):
                if explain:
                    why = self.assignment_reasons(job, engineer)
                    raise ValueError(
                        f"Назначение невыполнимо: {job.source_id or job.id}, {engineer.name}: "
                        + "; ".join(why)
                    )
                return None
            minutes = self.matrix.minutes(engineer.transport, origin_index, idx)
            meters = self.matrix.meters(engineer.transport, origin_index, idx)
            arrival = cursor + minutes
            start = max(arrival, job.window_start)
            lock = self.locks.get(job.id, {})
            if "start" in lock:
                if start > lock["start"]:
                    if explain:
                        raise ValueError(
                            f"Фиксация {job.source_id or job.id}: прибытие возможно в {hhmm(start)}, позже фиксированного начала {hhmm(lock['start'])}"
                        )
                    return None
                start = lock["start"]
            finish = start + job.duration_minutes
            if start > job.window_end or finish > end_shift:
                if explain:
                    conflicts = []
                    if start > job.window_end:
                        conflicts.append(
                            f"начало {hhmm(start)} позже конца окна {hhmm(job.window_end)} (дорога {minutes} мин)"
                        )
                    if finish > end_shift:
                        conflicts.append(
                            f"завершение {hhmm(finish)} позже конца доступности {hhmm(end_shift)}"
                        )
                    raise ValueError(
                        f"Назначение невыполнимо: {job.source_id or job.id}, {engineer.name}: "
                        + "; ".join(conflicts)
                    )
                return None
            reasons = [
                f"Навык: {SKILL_LABELS[job.required_skill]}",
                f"Начало {hhmm(start)} внутри окна {hhmm(job.window_start)}-{hhmm(job.window_end)}",
                f"Работа {job.duration_minutes} мин., завершение {hhmm(finish)} до конца смены {hhmm(end_shift)}",
                f"Переезд {minutes} мин. от предыдущей точки",
            ]
            if job.required_transport:
                reasons.append("Транспорт соответствует: " + TRANSPORT_LABELS[job.required_transport])
            if requirements(job, self.ds.settings):
                reasons.append(
                    "Дневной комплект содержит: " + ", ".join(sorted(requirements(job, self.ds.settings)))
                )
            level = priority_level(job)
            if level == 2:
                if is_emergency(job.work_type):
                    reasons.append("Приоритет 1: авария")
                else:
                    reasons.append("Приоритет 1: срочность диспетчера")
            elif level == 1:
                reasons.append("Приоритет 2: подключение")
            stop = {
                "job_id": job.id,
                "engineer_id": engineer.id,
                "arrival": arrival,
                "start": start,
                "finish": finish,
                "departure": cursor,
                "travel_minutes": minutes,
                "distance_m": meters,
                "waiting_minutes": start - arrival,
                "explanation": reasons,
                "locked": bool(lock),
            }
            stops.append(stop)
            legs.append(
                {
                    "from": origin,
                    "to": job.location.model_dump(),
                    "departure": cursor,
                    "arrival": arrival,
                    "distance_m": meters,
                    "job_id": job.id,
                }
            )
            cursor, origin_index, origin = finish, idx, job.location.model_dump()
        return stops, legs


def hhmm(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def baseline_orders(ctx):
    orders = [[] for _ in ctx.engineers]
    for idx, job in enumerate(ctx.jobs):
        for vehicle in range(len(ctx.engineers)):
            if ctx.schedule(vehicle, orders[vehicle] + [idx]) is not None:
                orders[vehicle].append(idx)
                break
    return orders


def objective(ctx, orders, previous=None):
    assigned = {i for order in orders for i in order}
    accidents = sum(priority_level(ctx.jobs[i]) == 2 for i in assigned)
    connections = sum(priority_level(ctx.jobs[i]) == 1 for i in assigned)
    used = sum(
        bool(order or ctx.states[e.id]["stops"] or ctx.states[e.id]["legs"])
        for e, order in zip(ctx.engineers, orders)
    )
    meters, changes, sla = 0, 0, 0
    for vehicle, order in enumerate(orders):
        scheduled = ctx.schedule(vehicle, order)
        if scheduled is None:
            return (float("inf"),)
        stops, legs = scheduled
        meters += sum(leg["distance_m"] for leg in legs)
        for position, stop in enumerate(stops):
            job = ctx.jobs[ctx.job_index[stop["job_id"]]]
            if ctx.ds.settings.sla_enabled and job.sla_deadline is not None:
                sla += max(0, stop[ctx.ds.settings.sla_basis] - job.sla_deadline)
            if previous and stop["job_id"] in previous:
                old = previous[stop["job_id"]]
                predecessor = stops[position - 1]["job_id"] if position else None
                changes += int(old["engineer_id"] != stop["engineer_id"])
                changes += int(old.get("predecessor") != predecessor)
    return (
        -len(assigned),
        used,
        -accidents,
        -connections,
        meters,
        sla * ctx.ds.settings.sla_penalty + changes * ctx.ds.settings.change_penalty,
    )


def optimize_orders(ctx, previous=None):
    n, vehicles = len(ctx.jobs), len(ctx.engineers)
    base = baseline_orders(ctx)
    if not n or not vehicles:
        return base, "feasible", 0
    sink = n + vehicles
    manager = pywrapcp.RoutingIndexManager(
        sink + 1, vehicles, list(range(n, n + vehicles)), [sink] * vehicles
    )
    routing = pywrapcp.RoutingModel(manager)
    matrix = ctx.matrix
    # Safe domination bounds, computed from this instance (not arbitrary magic weights).
    secondary_bound = (n * (3 * ctx.ds.settings.change_penalty + 1440 * ctx.ds.settings.sla_penalty)) + 1
    distance_unit = 100
    max_leg = max(
        matrix.meters(e.transport, a, b)
        for e in ctx.engineers
        for a in range(n + vehicles)
        for b in range(n + vehicles)
    )
    max_leg_cost = (max_leg + distance_unit - 1) // distance_unit
    connection_tier = ((n + vehicles) * max_leg_cost + 1) * secondary_bound
    accident_tier = (n + 1) * connection_tier
    engineer_cost = (n + 1) * accident_tier
    assignment_tier = (vehicles + 1) * engineer_cost
    if assignment_tier * (n + 2) >= 8_000_000_000_000_000_000:
        raise ValueError("Слишком большая география для безопасного масштаба целевой функции")
    transit_callbacks = []
    for vehicle, engineer in enumerate(ctx.engineers):

        def transit(a, b, e=engineer):
            x, y = manager.IndexToNode(a), manager.IndexToNode(b)
            if x == sink:
                return 0
            service = ctx.jobs[x].duration_minutes if x < n else 0
            return service + (matrix.minutes(e.transport, x, y) if y != sink else 0)

        def cost(a, b, e=engineer):
            x, y = manager.IndexToNode(a), manager.IndexToNode(b)
            if y == sink or x == sink:
                return 0
            # Sub-100-metre routing precision is unnecessary; 100 m units keep
            # all lexicographic tiers safely inside OR-Tools' signed int64 costs.
            distance_cost = (matrix.meters(e.transport, x, y) + distance_unit - 1) // distance_unit
            value = distance_cost * secondary_bound
            if previous and y < n and ctx.jobs[y].id in previous:
                old = previous[ctx.jobs[y].id]
                predecessor = ctx.jobs[x].id if x < n else None
                value += ctx.ds.settings.change_penalty * (
                    int(old["engineer_id"] != e.id) + int(old.get("predecessor") != predecessor)
                )
            return value

        transit_callbacks.append(routing.RegisterTransitCallback(transit))
        routing.SetArcCostEvaluatorOfVehicle(routing.RegisterTransitCallback(cost), vehicle)
        # An engineer with preserved work is already used; do not penalize using them twice.
        if not ctx.states[engineer.id]["stops"] and not ctx.states[engineer.id]["legs"]:
            routing.SetFixedCostOfVehicle(engineer_cost, vehicle)
    routing.AddDimensionWithVehicleTransits(transit_callbacks, 1440, 2880, False, "Time")
    dimension = routing.GetDimensionOrDie("Time")
    for idx, job in enumerate(ctx.jobs):
        index = manager.NodeToIndex(idx)
        dimension.CumulVar(index).SetRange(job.window_start, job.window_end)
        allowed = [v for v, e in enumerate(ctx.engineers) if ctx.can_assign(job, e)]
        if not allowed:
            routing.ActiveVar(index).SetValue(0)
        else:
            # OR-Tools 9.15 Python Span binding does not accept lists on some platforms.
            # Restrict the integer domain directly, keeping -1 for an unperformed node.
            for vehicle in range(vehicles):
                if vehicle not in allowed:
                    routing.VehicleVar(index).RemoveValue(vehicle)
        level = priority_level(job)
        priority_penalty = accident_tier if level == 2 else connection_tier if level == 1 else 0
        penalty = assignment_tier + priority_penalty
        if job.id not in ctx.locks:
            routing.AddDisjunction([index], penalty)
        elif "start" in ctx.locks[job.id]:
            dimension.CumulVar(index).SetValue(ctx.locks[job.id]["start"])
        if ctx.ds.settings.sla_enabled and job.sla_deadline is not None:
            deadline = job.sla_deadline - (
                job.duration_minutes if ctx.ds.settings.sla_basis == "finish" else 0
            )
            dimension.SetCumulVarSoftUpperBound(index, max(0, deadline), ctx.ds.settings.sla_penalty)
    for vehicle, engineer in enumerate(ctx.engineers):
        available = max(ctx.states[engineer.id]["time"], engineer.shift_start)
        end = min(
            engineer.shift_end, engineer.unavailable_from if engineer.unavailable_from is not None else 1440
        )
        # No future work is possible after unavailability, but empty routes remain valid.
        end = max(available, end)
        dimension.CumulVar(routing.Start(vehicle)).SetValue(available)
        dimension.CumulVar(routing.End(vehicle)).SetRange(available, end)
        routing.AddVariableMinimizedByFinalizer(dimension.CumulVar(routing.End(vehicle)))
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.time_limit.seconds = ctx.ds.settings.time_limit_seconds
    params.solution_limit = ctx.ds.settings.solution_limit
    params.sat_parameters.num_search_workers = 1
    params.sat_parameters.random_seed = ctx.ds.settings.seed
    started = time.monotonic()
    solution = routing.SolveWithParameters(params)
    elapsed = time.monotonic() - started
    if solution is None:
        if ctx.locks:
            raise ValueError("Не найден допустимый план с зафиксированными назначениями")
        return base, "fallback", elapsed
    orders = []
    for vehicle in range(vehicles):
        index, order = routing.Start(vehicle), []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node < n:
                order.append(node)
            index = solution.Value(routing.NextVar(index))
        orders.append(order)
    # Independently reconstruct and validate times; never let an optimizer regression replace a better baseline.
    if not ctx.locks and objective(ctx, base, previous) < objective(ctx, orders, previous):
        orders = base
    status = "time_limit" if elapsed >= ctx.ds.settings.time_limit_seconds * 0.97 else "feasible"
    return orders, status, elapsed


def unassigned_reason(ctx, idx, orders):
    job = ctx.jobs[idx]
    static = [(e, ctx.assignment_reasons(job, e)) for e in ctx.engineers]
    compatible = [(v, e) for v, (e, reasons) in enumerate(static) if not reasons and ctx.can_assign(job, e)]
    if not compatible:
        reasons = sorted({reason for _, why in static for reason in why})
        return {
            "job_id": job.id,
            "code": "resources",
            "reasons": reasons or ["Заявка зафиксирована за другим инженером"],
            "evidence": [{"engineer_id": e.id, "reasons": why} for e, why in static],
        }
    if all(ctx.schedule(v, [idx]) is None for v, _ in compatible):
        return {
            "job_id": job.id,
            "code": "time",
            "reasons": [
                "Работа с переездом не помещается в окно начала, оставшуюся смену или период доступности"
            ],
            "evidence": [
                {
                    "engineer_id": e.id,
                    "available_from": ctx.states[e.id]["time"],
                    "shift_end": min(e.shift_end, e.unavailable_from or 1440),
                    "duration": job.duration_minutes,
                }
                for v, e in compatible
            ],
        }
    for v, _ in compatible:
        for pos in range(len(orders[v]) + 1):
            if ctx.schedule(v, orders[v][:pos] + [idx] + orders[v][pos:]) is not None:
                return {
                    "job_id": job.id,
                    "code": "search_limit",
                    "reasons": [
                        "В найденном варианте не назначена; допустимая вставка существует. Запустите более тщательный расчёт или назначьте вручную"
                    ],
                    "evidence": [{"engineer_id": ctx.engineers[v].id, "position": pos}],
                }
    return {
        "job_id": job.id,
        "code": "capacity",
        "reasons": [
            "В текущих маршрутах подходящих инженеров нет свободного интервала с учётом переездов; требуется перестановка или дополнительные ресурсы"
        ],
        "evidence": [{"engineer_id": e.id, "scheduled_jobs": len(orders[v])} for v, e in compatible],
    }


def build_plan(
    ds: Dataset,
    mode="optimized",
    storage=None,
    states=None,
    parent=None,
    event=None,
    locks=None,
    explicit_orders=None,
    job_states=None,
    working_engineer_ids=None,
):
    started = time.monotonic()
    ds = Dataset.model_validate(ds.model_dump())
    if parent and working_engineer_ids is None:
        working_engineer_ids = working_engineers(parent)
    ctx = Context(ds, storage, states, locks, working_engineer_ids)
    previous = {}
    if parent:
        for route in parent["routes"]:
            pred = None
            for stop in route["stops"]:
                previous[stop["job_id"]] = {**stop, "predecessor": pred}
                pred = stop["job_id"]
    if explicit_orders is not None:
        orders = [[ctx.job_index[j] for j in explicit_orders.get(e.id, [])] for e in ds.engineers]
        status, search_seconds = "feasible", 0
    elif mode == "baseline":
        orders, status, search_seconds = baseline_orders(ctx), "feasible", 0
    else:
        orders, status, search_seconds = optimize_orders(ctx, previous)
    routes, assigned = [], set(ctx.frozen_ids)
    for vehicle, engineer in enumerate(ctx.engineers):
        scheduled = ctx.schedule(vehicle, orders[vehicle], explain=True)
        if scheduled is None:
            raise ValueError(
                f"Маршрут инженера {engineer.name} невыполним: проверьте навык, транспорт, оборудование, окно, переезд, смену и фиксации. Предыдущий план сохранён."
            )
        stops, legs = scheduled
        state = ctx.states[engineer.id]
        combined = copy.deepcopy(state["stops"]) + stops
        for stop in combined[len(state["stops"]) :]:
            job = next(j for j in ds.jobs if j.id == stop["job_id"])
            if ds.settings.sla_enabled and job.sla_deadline is not None:
                slack = job.sla_deadline - stop[ds.settings.sla_basis]
                stop["sla_slack_minutes"] = slack
                stop["sla_status"] = (
                    "late" if slack < 0 else "risk" if slack <= ds.settings.sla_risk_buffer else "ok"
                )
                stop["explanation"].append(
                    f"Настраиваемый SLA ({ds.settings.sla_basis}): запас {slack} мин. Это отдельное мягкое правило, не окно начала."
                )
        for stop in combined:
            assigned.add(stop["job_id"])
        all_legs = copy.deepcopy(state["legs"]) + legs
        routes.append(
            {
                "engineer_id": engineer.id,
                "engineer_name": engineer.name,
                "transport": engineer.transport,
                "stops": combined,
                "legs": all_legs,
                "distance_m": sum(leg["distance_m"] for leg in all_legs),
                "travel_minutes": sum(leg["arrival"] - leg["departure"] for leg in all_legs),
                "work_minutes": sum(
                    stop["completed_at"] - stop.get("started_at", stop["start"])
                    if stop.get("status") == "completed"
                    else stop["finish"] - stop["start"]
                    for stop in combined
                ),
                "waiting_minutes": sum(stop["waiting_minutes"] for stop in combined),
                "frozen_count": len(state["stops"]),
                "anchor": {"location": state["location"], "time": state["time"]},
            }
        )
    unassigned = [
        unassigned_reason(ctx, idx, orders) for idx, job in enumerate(ctx.jobs) if job.id not in assigned
    ]
    inherited_states = copy.deepcopy(
        job_states if job_states is not None else parent.get("job_states", {}) if parent else {}
    )
    active_ids = {job.id for job in ds.jobs}
    inherited_states = {
        identifier: state for identifier, state in inherited_states.items() if identifier in active_ids
    }
    for route in routes:
        for stop in route["stops"]:
            state = inherited_states.setdefault(stop["job_id"], {"status": "sent", "updated_at": None})
            if state["status"] == "unassigned":
                state = {"status": "sent", "updated_at": None}
                inherited_states[stop["job_id"]] = state
            stop["status"] = state["status"]
            if state.get("started_at") is not None:
                stop["started_at"] = state["started_at"]
            if state.get("completed_at") is not None:
                stop["completed_at"] = state["completed_at"]
    for item in unassigned:
        inherited_states[item["job_id"]] = {"status": "unassigned", "updated_at": None}
    plan = {
        "id": str(uuid.uuid4()),
        "dataset_id": ds.id,
        "dataset_revision": ds.revision,
        "mode": mode,
        "version": parent["version"] + 1 if parent else 1,
        "parent_id": parent["id"] if parent else None,
        "status": status,
        "search_seconds": round(search_seconds, 3),
        "calculation_seconds": round(time.monotonic() - started, 3),
        "routing_method": ctx.matrix.method,
        "routing_notice": ctx.matrix.notice,
        "snapshot": ds.model_dump(),
        "routes": routes,
        "working_engineer_ids": sorted(
            working_engineer_ids
            if working_engineer_ids is not None
            else {route["engineer_id"] for route in routes if route["stops"] or route["legs"]}
        ),
        "unassigned": unassigned,
        "event": event,
        "locks": locks or {},
        "job_states": inherited_states,
        "changes": [],
        "metrics": {
            "assigned": len(assigned),
            "unassigned": len(unassigned),
            "total": len(ds.jobs),
            "urgent_assigned": sum(j.priority == "urgent" and j.id in assigned for j in ds.jobs),
            "accident_assigned": sum(is_emergency(j.work_type) and j.id in assigned for j in ds.jobs),
            "connection_assigned": sum(priority_level(j) == 1 and j.id in assigned for j in ds.jobs),
            "engineers_used": sum(bool(r["stops"] or r["legs"]) for r in routes),
            "distance_m": sum(r["distance_m"] for r in routes),
            "travel_minutes": sum(r["travel_minutes"] for r in routes),
            "work_minutes": sum(r["work_minutes"] for r in routes),
            "sla_late": sum(s.get("sla_status") == "late" for r in routes for s in r["stops"]),
            "sla_risk": sum(s.get("sla_status") == "risk" for r in routes for s in r["stops"]),
        },
        "objective": list(objective(ctx, orders, previous)),
    }
    if parent:
        plan["changes"] = diff_plans(parent, plan)
    errors = validate_plan(plan)
    if errors:
        raise ValueError("Нарушения плана: " + "; ".join(errors[:5]))
    return plan


def diff_plans(before, after):
    def assignments(plan):
        return {
            s["job_id"]: {
                "engineer_id": r["engineer_id"],
                "start": s["start"],
                "position": p,
                "status": s.get("status", "sent"),
            }
            for r in plan["routes"]
            for p, s in enumerate(r["stops"])
        }

    old, new = assignments(before), assignments(after)
    result = []
    for identifier in sorted(set(old) | set(new)):
        if old.get(identifier) != new.get(identifier):
            result.append(
                {
                    "job_id": identifier,
                    "before": old.get(identifier),
                    "after": new.get(identifier),
                    "kind": "added"
                    if identifier not in old
                    else "removed"
                    if identifier not in new
                    else "changed",
                }
            )
    return result


def freeze_states(parent, event_time, active_job_id=None):
    ds = Dataset.model_validate(parent["snapshot"])
    states = initial_states(ds)
    for route in parent["routes"]:
        state = states[route["engineer_id"]]
        active_positions = [
            index
            for index, stop in enumerate(route["stops"])
            if stop.get("status") in {"en_route", "in_progress"} or stop["job_id"] == active_job_id
        ]
        active_limit = min(active_positions, default=len(route["stops"]) - 1)
        last_frozen = max(
            (
                index
                for index, stop in enumerate(route["stops"])
                if index <= active_limit
                and (
                    stop["departure"] < event_time
                    or stop.get("status") in {"en_route", "in_progress", "completed"}
                    or stop["job_id"] == active_job_id
                )
            ),
            default=-1,
        )
        frozen = copy.deepcopy(route["stops"][: last_frozen + 1])
        state["stops"] = frozen
        freeze_until = max(
            event_time,
            max((s.get("expected_finish", s["finish"]) for s in frozen), default=event_time),
        )
        state["time"] = max(freeze_until, state["time"])
        frozen_ids = {stop["job_id"] for stop in frozen}
        for leg in route["legs"]:
            if leg["job_id"] not in frozen_ids:
                break
            if leg["departure"] >= freeze_until:
                break
            part = copy.deepcopy(leg)
            if leg["arrival"] > freeze_until:
                ratio = (freeze_until - leg["departure"]) / (leg["arrival"] - leg["departure"])
                part["to"] = {
                    key: leg["from"][key] + ratio * (leg["to"][key] - leg["from"][key])
                    for key in ("latitude", "longitude")
                }
                part["arrival"] = freeze_until
                part["distance_m"] = round(leg["distance_m"] * ratio)
                part["partial"] = True
            state["legs"].append(part)
            state["location"] = part["to"]
    return states


def validate_plan(plan):
    """Independent constraint checks before persistence, also used by acceptance tests."""
    ds = Dataset.model_validate(plan["snapshot"])
    jobs = {j.id: j for j in ds.jobs}
    engineers = {e.id: e for e in ds.engineers}
    errors, seen = [], set()
    roster = plan.get("working_engineer_ids")
    if roster is not None and (len(roster) != len(set(roster)) or set(roster) - engineers.keys()):
        errors.append("Некорректный состав рабочего дня")
    event_time = plan.get("event", {}).get("time", -1) if plan.get("event") else -1
    for route in plan["routes"]:
        engineer = engineers[route["engineer_id"]]
        finish = engineer.shift_start
        for position, stop in enumerate(route["stops"]):
            job = jobs[stop["job_id"]]
            if roster is not None and position >= route["frozen_count"] and engineer.id not in roster:
                errors.append(f"Инженер вне состава рабочего дня {job.id}")
            if job.id in seen:
                errors.append(f"Повтор заявки {job.id}")
            seen.add(job.id)
            if not job.window_start <= stop["start"] <= job.window_end:
                errors.append(f"Временное окно {job.id}")
            planned_finish = stop.get("planned_finish", stop["finish"])
            if planned_finish != stop["start"] + job.duration_minutes or planned_finish > engineer.shift_end:
                errors.append(f"Длительность/смена {job.id}")
            if stop.get("started_at") is not None and stop["started_at"] < job.window_start:
                errors.append(f"Фактическое начало до окна {job.id}")
            if stop.get("status") == "completed" and (
                stop.get("completed_at") != stop["finish"]
                or stop.get("started_at") is None
                or stop["finish"] < stop["started_at"]
            ):
                errors.append(f"Фактическое завершение {job.id}")
            if stop["start"] < stop["arrival"] or stop["arrival"] < finish:
                errors.append(f"Пересечение работ {job.id}")
            if stop["departure"] < finish or stop["arrival"] - stop["departure"] != stop["travel_minutes"]:
                errors.append(f"Время переезда {job.id}")
            if position >= route["frozen_count"] and stop["start"] > event_time:
                if job.service_area.casefold() != engineer.service_area.casefold():
                    errors.append(f"Чужой участок {job.id}")
                if eligible(job, engineer, ds.settings):
                    errors.append(f"Ресурсы {job.id}")
                if engineer.unavailable_from is not None and stop["finish"] > engineer.unavailable_from:
                    errors.append(f"Недоступность {job.id}")
            lock = plan.get("locks", {}).get(job.id)
            if lock and (
                engineer.id != lock["engineer_id"] or ("start" in lock and stop["start"] != lock["start"])
            ):
                errors.append(f"Нарушена фиксация {job.id}")
            finish = stop.get("expected_finish", stop["finish"])
        if route["distance_m"] != sum(leg["distance_m"] for leg in route["legs"]):
            errors.append("Пробег маршрута")
    unassigned = {j["job_id"] for j in plan["unassigned"]}
    if seen & unassigned or seen | unassigned != set(jobs):
        errors.append("Полнота назначений")
    if any(not item["reasons"] for item in plan["unassigned"]):
        errors.append("Нет причины неназначения")
    if set(plan.get("locks", {})) - seen:
        errors.append("Зафиксированная заявка не назначена")
    if plan["metrics"]["distance_m"] != sum(r["distance_m"] for r in plan["routes"]):
        errors.append("Суммарный пробег")
    if (
        plan["metrics"]["assigned"] != len(seen)
        or plan["metrics"]["unassigned"] != len(unassigned)
        or plan["metrics"]["total"] != len(jobs)
    ):
        errors.append("Счётчики заявок")
    if plan["metrics"]["travel_minutes"] != sum(
        leg["arrival"] - leg["departure"] for route in plan["routes"] for leg in route["legs"]
    ):
        errors.append("Суммарное время в дороге")
    return errors
