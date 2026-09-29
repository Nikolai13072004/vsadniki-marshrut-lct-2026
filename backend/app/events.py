"""Immutable day changes. Historical stops are never rewritten by an event."""

import copy

from .models import Dataset, Job
from .planner import Context, build_plan, eligible, freeze_states, validate_plan, working_engineers


def event_context(parent, event_time, active_job_id=None):
    if parent.get("event") and event_time < parent["event"]["time"]:
        raise ValueError("Событие не может предшествовать предыдущему")
    ds = Dataset.model_validate(parent["snapshot"])
    states = freeze_states(parent, event_time, active_job_id)
    frozen = {s["job_id"] for state in states.values() for s in state["stops"]}
    return ds, states, frozen


def insert_without_replanning(ds, parent, states, frozen, event, locks, job_states, storage):
    """Insert one ordinary job while keeping every existing future stop unchanged."""
    original_locks = copy.deepcopy(locks)
    temporary_locks = copy.deepcopy(locks)
    existing_orders = {}
    for route in parent["routes"]:
        future = [stop for stop in route["stops"] if stop["job_id"] not in frozen]
        existing_orders[route["engineer_id"]] = [stop["job_id"] for stop in future]
        for stop in future:
            temporary_locks[stop["job_id"]] = {
                "engineer_id": route["engineer_id"],
                "start": stop["start"],
            }

    context = Context(ds, storage, states, temporary_locks, working_engineers(parent))
    new_job_id = event["job"]["id"]
    new_index = context.job_index[new_job_id]
    best = None
    for vehicle, engineer in enumerate(context.engineers):
        current = [context.job_index[job_id] for job_id in existing_orders[engineer.id]]
        current_schedule = context.schedule(vehicle, current)
        current_distance = sum(leg["distance_m"] for leg in current_schedule[1]) if current_schedule else 0
        for position in range(len(current) + 1):
            candidate = current[:position] + [new_index] + current[position:]
            scheduled = context.schedule(vehicle, candidate)
            if scheduled is None:
                continue
            stops, legs = scheduled
            inserted = next(stop for stop in stops if stop["job_id"] == new_job_id)
            added_distance = sum(leg["distance_m"] for leg in legs) - current_distance
            score = (added_distance, inserted["start"], engineer.id)
            if best is None or score < best[0]:
                orders = copy.deepcopy(existing_orders)
                orders[engineer.id].insert(position, new_job_id)
                best = (score, orders)

    selected_orders = best[1] if best else existing_orders
    event["inserted"] = best is not None
    event["notice"] = (
        "Новая обычная заявка добавлена в свободный интервал. Остальные назначения и время начала сохранены."
        if best
        else "Свободного интервала для новой обычной заявки нет. Существующий план оставлен без изменений."
    )
    result = build_plan(
        ds,
        storage=storage,
        states=states,
        parent=parent,
        event=event,
        locks=temporary_locks,
        explicit_orders=selected_orders,
        job_states=job_states,
    )
    # These locks are temporary insertion constraints. Only user-created locks
    # should affect later emergency replanning.
    result["locks"] = original_locks
    for route in result["routes"]:
        for stop in route["stops"]:
            stop["locked"] = stop["job_id"] in original_locks
    return result


def apply_event(parent, event, storage):
    active_job_id = event.job_id if event.type in {"status", "complete"} else None
    ds, states, frozen = event_context(parent, event.time, active_job_id)
    locks = {key: dict(value) for key, value in parent.get("locks", {}).items()}
    job_states = copy.deepcopy(parent.get("job_states", {}))
    audit = event.model_dump(exclude_none=True)
    if event.type in {"new", "urgent"}:
        if event.demo:
            end = min(
                ds.settings.shift_end - ds.settings.demo_urgent_duration,
                event.time + ds.settings.demo_urgent_window,
            )
            if end < event.time:
                raise ValueError("До конца смены недостаточно времени для демонстрационной заявки")
            event.job = Job(
                id=f"urgent-{parent['version']}",
                source_id=f"СРОЧНАЯ-{parent['version']}",
                address=ds.office_address,
                service_area=next((job.service_area for job in ds.jobs if job.service_area), ds.region),
                location=ds.office_location,
                geo_quality=ds.office_geo_quality,
                geo_note=ds.office_geo_note,
                work_type="Авария",
                bk_type="Глобальная проблема",
                window_start=event.time,
                window_end=end,
                duration_minutes=ds.settings.demo_urgent_duration,
                required_skill="emergency",
                priority="urgent",
                provenance={
                    "location": "computed",
                    "priority": "synthetic",
                    "duration_minutes": "configured",
                    "required_skill": "synthetic",
                },
            )
        if event.job is None:
            raise ValueError("Для новой заявки нужны все её поля")
        if event.job.id in {j.id for j in ds.jobs}:
            raise ValueError("Заявка с таким ID уже существует")
        if event.job.location is None:
            raise ValueError("Укажите координаты срочной заявки")
        if event.job.window_end < event.time:
            raise ValueError("Окно новой заявки завершилось до события")
        event.job.priority = "urgent" if event.type == "urgent" else "normal"
        ds.jobs.append(event.job)
        audit["job"] = event.job.model_dump()
    elif event.type == "cancel":
        job = next((j for j in ds.jobs if j.id == event.job_id), None)
        if job is None:
            raise ValueError("Заявка для отмены не найдена")
        current = job_states.get(job.id, {}).get("status", "sent")
        if job.id in frozen or current in {"in_progress", "completed"}:
            raise ValueError("Нельзя отменить начатую или выполненную работу")
        audit["cancelled_job"] = job.model_dump()
        audit["previous_status"] = current
        audit["new_status"] = "cancelled"
        audit["notice"] = "Заявка отменена диспетчером и исключена из маршрутов."
        ds.jobs = [j for j in ds.jobs if j.id != job.id]
        locks.pop(job.id, None)
        job_states.pop(job.id, None)
    elif event.type == "status":
        job = next((j for j in ds.jobs if j.id == event.job_id), None)
        if job is None:
            raise ValueError("Заявка для изменения статуса не найдена")
        stop = next(
            (stop for route in parent["routes"] for stop in route["stops"] if stop["job_id"] == job.id),
            None,
        )
        if stop is None:
            raise ValueError("Статус можно изменить только у назначенной заявки")
        current = job_states.get(job.id, {}).get("status", stop.get("status", "sent"))
        expected = {"en_route": "sent", "in_progress": "en_route"}[event.job_status]
        if current != expected:
            raise ValueError("Статусы меняются последовательно: отправлена - в пути - выполнение")
        earliest = stop["departure"] if event.job_status == "en_route" else stop["start"]
        if event.time < earliest:
            raise ValueError("Этот статус нельзя поставить раньше запланированного этапа маршрута")
        state = states[stop["engineer_id"]]
        frozen_stop = next((item for item in state["stops"] if item["job_id"] == job.id), None)
        if frozen_stop is None:
            raise ValueError("Сначала завершите предыдущую работу инженера")
        remaining_travel = max(0, stop["arrival"] - event.time) if event.job_status == "en_route" else 0
        expected_finish = max(stop["finish"], event.time + remaining_travel + job.duration_minutes)
        frozen_stop["expected_finish"] = expected_finish
        frozen_stop["status_updated_at"] = event.time
        state["time"] = max(state["time"], expected_finish)
        next_state = {
            **job_states.get(job.id, {}),
            "status": event.job_status,
            "updated_at": event.time,
        }
        if event.job_status == "in_progress":
            next_state["started_at"] = event.time
            if event.time > job.window_end:
                frozen_stop["explanation"].append(
                    "Фактическое начало позже окна клиента; нарушение сохранено в истории."
                )
        job_states[job.id] = next_state
        locks[job.id] = {"engineer_id": stop["engineer_id"], "start": stop["start"]}
        audit["previous_status"] = current
        audit["new_status"] = event.job_status
        audit["status_job"] = job.model_dump()
        audit["notice"] = (
            "Инженер выехал к клиенту; назначение закреплено."
            if event.job_status == "en_route"
            else "Выполнение началось; заявка исключена из перестановок."
        )
    elif event.type == "complete":
        job = next((j for j in ds.jobs if j.id == event.job_id), None)
        if job is None:
            raise ValueError("Заявка для завершения не найдена")
        completed_stop = next(
            (stop for state in states.values() for stop in state["stops"] if stop["job_id"] == job.id),
            None,
        )
        current = job_states.get(job.id, {}).get(
            "status", completed_stop.get("status", "sent") if completed_stop else "unassigned"
        )
        if completed_stop is None or current != "in_progress":
            raise ValueError("Завершить можно только заявку в статусе «Выполнение»")
        if event.time < job_states[job.id].get("started_at", event.time):
            raise ValueError("Время завершения раньше начала выполнения")
        completed_stop["status"] = "completed"
        if event.time != completed_stop["finish"]:
            completed_stop["planned_finish"] = completed_stop["finish"]
        completed_stop["finish"] = event.time
        completed_stop["completed_at"] = event.time
        completed_stop.pop("expected_finish", None)
        states[completed_stop["engineer_id"]]["time"] = event.time
        completed_stop["explanation"].append(
            "Фактическое завершение: " + f"{event.time // 60:02d}:{event.time % 60:02d}"
        )
        job_states[job.id] = {
            **job_states.get(job.id, {}),
            "status": "completed",
            "updated_at": event.time,
            "completed_at": event.time,
        }
        locks.pop(job.id, None)
        audit["completed_job"] = job.model_dump()
        audit["previous_status"] = current
        audit["new_status"] = "completed"
        audit["notice"] = "Заявка отмечена выполненной и исключена из дальнейшего перепланирования."
    elif event.type == "reschedule":
        job = next((j for j in ds.jobs if j.id == event.job_id), None)
        if job is None:
            raise ValueError("Заявка для переноса не найдена")
        if job.id in frozen:
            raise ValueError("Нельзя переносить начатую или выполненную работу")
        if event.window_end < event.time:
            raise ValueError("Новое окно уже завершилось к моменту события")
        audit["previous_window"] = {
            "start": job.window_start,
            "end": job.window_end,
        }
        job.window_start = event.window_start
        job.window_end = event.window_end
        audit["new_window"] = {
            "start": job.window_start,
            "end": job.window_end,
        }
        audit["rescheduled_job"] = job.model_dump()
        audit["notice"] = "Временное окно клиента обновлено; будущие маршруты пересчитаны."
    else:
        engineer = next((e for e in ds.engineers if e.id == event.engineer_id), None)
        if engineer is None:
            raise ValueError("Инженер не найден")
        if not engineer.available:
            raise ValueError("Инженер уже недоступен")
        engineer.available = False
        engineer.unavailable_from = event.time
        released = [
            key for key, value in locks.items() if value["engineer_id"] == engineer.id and key not in frozen
        ]
        for key in released:
            locks.pop(key)
        audit["released_locks"] = released
        audit["notice"] = (
            "Начатая работа сохраняется до завершения. Будущие назначения освобождены; новых выездов у недоступного инженера нет."
        )
    ds = Dataset.model_validate(ds.model_dump())
    if event.type == "new":
        return insert_without_replanning(
            ds,
            parent,
            states,
            frozen,
            audit,
            locks,
            job_states,
            storage,
        )
    return build_plan(
        ds,
        storage=storage,
        states=states,
        parent=parent,
        event=audit,
        locks=locks,
        job_states=job_states,
    )


def assign_manually(parent, request, storage):
    ds, states, frozen = event_context(parent, request.time)
    if request.job_id in frozen:
        raise ValueError("Нельзя переназначить начатую или выполненную работу")
    if request.job_id not in {j.id for j in ds.jobs}:
        raise ValueError("Заявка не найдена")
    if request.engineer_id not in {e.id for e in ds.engineers}:
        raise ValueError("Инженер не найден")
    job = next(job for job in ds.jobs if job.id == request.job_id)
    engineer = next(engineer for engineer in ds.engineers if engineer.id == request.engineer_id)
    resource_errors = eligible(job, engineer, ds.settings)
    if resource_errors:
        raise ValueError("Назначение невыполнимо: " + "; ".join(resource_errors))
    roster = working_engineers(parent)
    activation = engineer.id not in roster
    if activation and not request.activate_engineer:
        raise ValueError("Инженер не задействован в плане дня. Подтвердите его отдельный вызов диспетчером")
    if activation:
        roster.add(engineer.id)
    orders = {
        r["engineer_id"]: [
            s["job_id"] for s in r["stops"] if s["job_id"] not in frozen and s["job_id"] != request.job_id
        ]
        for r in parent["routes"]
    }
    if request.position > len(orders[request.engineer_id]):
        raise ValueError("Позиция выходит за пределы оставшегося маршрута")
    orders[request.engineer_id].insert(request.position, request.job_id)
    locks = {key: dict(value) for key, value in parent.get("locks", {}).items() if key != request.job_id}
    result = build_plan(
        ds,
        mode="manual",
        storage=storage,
        states=states,
        parent=parent,
        event={
            "type": "manual",
            **request.model_dump(),
            "engineer_activated": activation,
            "notice": (
                "Диспетчер отдельно подтвердил вызов инженера и ручное назначение."
                if activation
                else "Ручное назначение проверено в пределах состава рабочего дня."
            ),
        },
        locks=locks,
        explicit_orders=orders,
        working_engineer_ids=roster,
    )
    stop = next(s for r in result["routes"] for s in r["stops"] if s["job_id"] == request.job_id)
    if request.lock:
        result["locks"][request.job_id] = {"engineer_id": request.engineer_id, "start": stop["start"]}
        stop["locked"] = True
        stop["explanation"].append(
            "Ручное назначение проверено; инженер и начало зафиксированы для следующих пересчётов."
        )
    errors = validate_plan(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result
