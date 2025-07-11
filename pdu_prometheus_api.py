import asyncio
import yaml
from fastapi import FastAPI, Response
from datetime import datetime
from prometheus_client import Gauge, Counter, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest
from pysnmp.hlapi.asyncio import nextCmd, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity

# Load configuration from YAML
with open("config.yaml") as f:
    config = yaml.safe_load(f)

PDUS = config['pdus']
COMMUNITY = 'public'

# Prometheus registry and metrics
registry = CollectorRegistry()
VOLTAGE_GAUGE = Gauge('pdu_voltage', 'Voltage reading', ['pdu_ip', 'oid'], registry=registry)
CURRENT_GAUGE = Gauge('pdu_current', 'Current reading', ['pdu_ip', 'server', 'oid'], registry=registry)
ENERGY_COUNTER = Counter('pdu_energy', 'Energy reading (Wh)', ['pdu_ip', 'oid'], registry=registry)
SNMP_FAILURES = Counter('snmp_failures', 'SNMP failures', ['pdu_ip', 'oid'], registry=registry)

# Async SNMP walk
async def snmp_walk(ip, base_oid):
    results = []
    try:
        async for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
            CommunityData(COMMUNITY),
            UdpTransportTarget((ip, 161), timeout=1, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(base_oid)),
            lexicographicMode=False
        ):
            if errorIndication or errorStatus:
                for varBind in varBinds:
                    oid, _ = varBind
                    SNMP_FAILURES.labels(pdu_ip=ip, oid=str(oid)).inc()
                break
            for varBind in varBinds:
                oid, val = varBind
                results.append((str(oid), float(str(val))))
    except Exception:
        SNMP_FAILURES.labels(pdu_ip=ip, oid=base_oid).inc()
    return results

# Poll all metrics using SNMP walk for each PDU
async def poll_device(pdu):
    ip = pdu['ip']
    voltage_oid = pdu['voltage_oid']
    energy_oid = pdu['energy_oid']
    servers = pdu.get('servers', [])

    voltage_results = await snmp_walk(ip, voltage_oid)
    for oid, val in voltage_results:
        VOLTAGE_GAUGE.labels(pdu_ip=ip, oid=oid).set(val)

    energy_results = await snmp_walk(ip, energy_oid)
    for oid, val in energy_results:
        ENERGY_COUNTER.labels(pdu_ip=ip, oid=oid).inc(val * 10)

    for server in servers:
        name = server['name']
        current_oid = server['current_oid']
        current_results = await snmp_walk(ip, current_oid)
        for oid, val in current_results:
            CURRENT_GAUGE.labels(pdu_ip=ip, server=name, oid=oid).set(val * 0.001)

# Periodic poll loop
async def poll_loop():
    while True:
        tasks = [poll_device(pdu) for pdu in PDUS]
        await asyncio.gather(*tasks)
        await asyncio.sleep(30)

# FastAPI app
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_loop())

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
