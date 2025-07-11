import asyncio
import yaml
from fastapi import FastAPI, Response
from datetime import datetime
from prometheus_client import Gauge, Counter, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest
from pysnmp.hlapi.asyncio import nextCmd, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity

# Load configuration from YAML
with open("config.yaml") as f:
    config = yaml.safe_load(f)

PDU_IP = config['pdu']['ip']
VOLTAGE_OID = config['pdu']['voltage_oid']
ENERGY_OID = config['pdu']['energy_oid']
SERVERS = config['pdu']['servers']
COMMUNITY = 'public'

# Prometheus registry and metrics
registry = CollectorRegistry()
VOLTAGE_GAUGE = Gauge('pdu_voltage', 'Voltage reading', ['ip', 'oid'], registry=registry)
CURRENT_GAUGE = Gauge('pdu_current', 'Current reading', ['ip', 'server', 'oid'], registry=registry)
ENERGY_COUNTER = Counter('pdu_energy', 'Energy reading (Wh)', ['ip', 'oid'], registry=registry)
SNMP_FAILURES = Counter('snmp_failures', 'SNMP failures', ['ip', 'oid'], registry=registry)

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
                    SNMP_FAILURES.labels(ip=ip, oid=str(oid)).inc()
                break
            for varBind in varBinds:
                oid, val = varBind
                results.append((str(oid), float(str(val))))
    except Exception:
        SNMP_FAILURES.labels(ip=ip, oid=base_oid).inc()
    return results

# Poll all metrics using SNMP walk
async def poll_device():
    # Walk voltage
    voltage_results = await snmp_walk(PDU_IP, VOLTAGE_OID)
    for oid, val in voltage_results:
        VOLTAGE_GAUGE.labels(ip=PDU_IP, oid=oid).set(val)

    # Walk energy
    energy_results = await snmp_walk(PDU_IP, ENERGY_OID)
    for oid, val in energy_results:
        ENERGY_COUNTER.labels(ip=PDU_IP, oid=oid).inc(val * 10)  # kWh to Wh

    # Walk current for each server
    for server in SERVERS:
        name = server['name']
        base_oid = server['current_oid']
        current_results = await snmp_walk(PDU_IP, base_oid)
        for oid, val in current_results:
            CURRENT_GAUGE.labels(ip=PDU_IP, server=name, oid=oid).set(val * 0.001)  # mA to A

# Periodic poll loop
async def poll_loop():
    while True:
        await poll_device()
        await asyncio.sleep(30)  # wait before next cycle

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
