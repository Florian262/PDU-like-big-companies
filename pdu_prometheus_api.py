import asyncio
from fastapi import FastAPI, Response
from datetime import datetime
from prometheus_client import Gauge, Counter, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest
from pysnmp.hlapi.asyncio import getCmd, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
import ipaddress

# Configuration
COMMUNITY = 'public'
IP_RANGE = '10.150.0.0/22'
OID_MAP = {
    'voltage': '1.3.6.1.4.1.42578.1.2.2.0',
    'current1': '1.3.6.1.4.1.42578.1.3.2.3.0',
    'current2': '1.3.6.1.4.1.42578.1.3.4.3.0',
    'current3': '1.3.6.1.4.1.42578.1.3.6.3.0',
    'current4': '1.3.6.1.4.1.42578.1.3.8.3.0',
    'energy': '1.3.6.1.4.1.42578.1.2.5.0'
}

# Prometheus registry and metrics
registry = CollectorRegistry()
VOLTAGE_GAUGE = Gauge('pdu_voltage', 'Voltage reading', ['ip'], registry=registry)
CURRENT_GAUGE = Gauge('pdu_current', 'Current reading', ['ip', 'port'], registry=registry)
ENERGY_COUNTER = Counter('pdu_energy', 'Energy reading (Wh)', ['ip'], registry=registry)
SNMP_FAILURES = Counter('snmp_failures', 'SNMP failures', ['ip', 'oid'], registry=registry)

# Async SNMP get
async def snmp_get(ip, oid):
    try:
        errorIndication, errorStatus, errorIndex, varBinds = await getCmd(
            CommunityData(COMMUNITY),
            UdpTransportTarget((ip, 161), timeout=1, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        if errorIndication or errorStatus:
            SNMP_FAILURES.labels(ip=ip, oid=oid).inc()
            return None
        for varBind in varBinds:
            return float(str(varBind[1]))
    except Exception:
        SNMP_FAILURES.labels(ip=ip, oid=oid).inc()
        return None

# Poll all metrics for one device
async def poll_device(ip):
    voltage = await snmp_get(ip, OID_MAP['voltage'])
    if voltage:
        VOLTAGE_GAUGE.labels(ip=ip).set(voltage)

    energy = await snmp_get(ip, OID_MAP['energy'])
    if energy:
        ENERGY_COUNTER.labels(ip=ip).inc(energy * 10)  # Convert kWh to Wh

    for i in range(1, 5):
        current_oid = OID_MAP[f'current{i}']
        current_val = await snmp_get(ip, current_oid)
        if current_val:
            CURRENT_GAUGE.labels(ip=ip, port=f'{i}').set(current_val * 0.001)  # mA to A

# Periodic poll loop
async def poll_loop():
    while True:
        all_ips = [str(ip) for ip in ipaddress.ip_network(IP_RANGE)]
        tasks = [poll_device(ip) for ip in all_ips]
        await asyncio.gather(*tasks)
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
