import asyncio
from asyncio import CancelledError

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from websockets.exceptions import ConnectionClosedOK

from ataka.common import queue, database
from ataka.common.database.models import Job, Target, Flag
from ataka.common.queue import FlagNotifyQueue, ControlQueue, ControlAction, ControlMessage
from ataka.common.queue.output import OutputMessage, OutputQueue
from ataka.web.schemas import FlagSubmission
from ataka.web.websocket_handlers import handle_incoming, handle_websocket_connection

app = FastAPI()


ctf_config = None
ctf_config_task = None


async def listen_for_ctf_config():
    async with await queue.get_channel() as channel:
        control_queue = await ControlQueue.get(channel)

        async def wait_for_updates():
            global ctf_config
            async for message in control_queue.wait_for_messages():
                match message.action:
                    case ControlAction.CTF_CONFIG_UPDATE:
                        ctf_config = message.extra

        wait_task = asyncio.create_task(wait_for_updates())

        await control_queue.send_message(ControlMessage(action=ControlAction.GET_CTF_CONFIG))

        await wait_task


@app.on_event("startup")
async def startup_event():
    await queue.connect()
    await database.connect()

    global ctf_config_task
    ctf_config_task = asyncio.create_task(listen_for_ctf_config())


@app.on_event("shutdown")
async def shutdown_event():
    await queue.disconnect()
    await database.disconnect()


async def get_session():
    async with database.get_session() as session:
        yield session


async def get_channel():
    async with await queue.get_channel() as channel:
        yield channel


@app.get("/api/targets")
async def all_targets(session: Session = Depends(get_session)):
    get_targets = select(Target).limit(100)
    target_objs = (await session.execute(get_targets)).scalars()
    targets = [x.to_dict() for x in target_objs]

    return targets


@app.get("/api/targets/service/{service_name}")
async def targets_by_service(service_name, session: Session = Depends(get_session)):
    get_targets = select(Target).where(Target.service == service_name).limit(100)
    target_objs = (await session.execute(get_targets)).scalars()
    targets = [x.to_dict() for x in target_objs]

    return targets


@app.get("/api/targets/ip/{ip_addr}")
async def targets_by_ip(ip_addr, session: Session = Depends(get_session)):
    get_targets = select(Target).where(Target.ip == ip_addr).limit(100)
    target_objs = (await session.execute(get_targets)).scalars()
    targets = [x.to_dict() for x in target_objs]

    return targets


@app.get("/api/jobs")
async def all_jobs(session: Session = Depends(get_session)):
    get_jobs = select(Job)
    job_objs = (await session.execute(get_jobs)).scalars()
    jobs = [x.to_dict() for x in job_objs]

    return jobs


@app.get("/api/job/{job_id}/status")
async def get_job(job_id, session: Session = Depends(get_session)):
    get_jobs = select(Job).where(Job.id == job_id).limit(1)
    job_obj = (await session.execute(get_jobs)).scalars().first()

    return job_obj.to_dict()


@app.get("/api/flags")
async def all_flags(session: Session = Depends(get_session)):
    # TODO
    return []


@app.get("/api/services")
async def all_flags():
    global ctf_config
    if ctf_config is None:
        return []
    return ctf_config["services"]


@app.post("/api/flag/submit")
async def submit_flag(submission: FlagSubmission, session: Session = Depends(get_session), channel=Depends(get_channel)):
    manual_id = 0

    results = []

    async def listen_for_responses():
        flag_notify_queue = await FlagNotifyQueue.get(channel)
        try:
            async for message in flag_notify_queue.wait_for_messages():
                if message.manual_id == manual_id:
                    results.append(message.flag_id)
        except CancelledError:
            pass

    task = asyncio.create_task(listen_for_responses())

    message = OutputMessage(manual_id=manual_id, execution_id=None, stdout=True, output=submission.flags)
    output_queue = await OutputQueue.get(channel)
    await output_queue.send_message(message)

    try:
        await asyncio.wait_for(task, 3)
    except TimeoutError:
        pass

    get_result_flags = select(Flag).where(Flag.id.in_(results))
    flags = (await session.execute(get_result_flags)).scalars()

    return [x.to_dict() for x in flags]


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket, channel=Depends(get_channel)):
    await websocket.accept()

    try:
        await handle_websocket_connection(websocket, channel)
    except WebSocketDisconnect:
        pass
    except ConnectionClosedOK:
        pass