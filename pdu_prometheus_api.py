from typing import Dict
from datetime import datetime

# Represents one PDU
class PDU:
    def __init__(self, id: str, voltage_zones: Dict[str, float]):
        self.id = id
        self.voltage_zones = voltage_zones
        self.socket_currents: Dict[int, float] = {}
        self.energy_log: Dict[int, float] = {}

    def update_currents(self, new_currents: Dict[int, float]):
        self.socket_currents = new_currents

    def compute_power(self) -> Dict[int, float]:
        power = {}
        for s_id, current in self.socket_currents.items():
            zone = "1-12" if s_id <= 12 else "13-24"
            voltage = self.voltage_zones[zone]
            power[s_id] = voltage * current
        return power

    def update_energy(self, duration_sec: float):
        power = self.compute_power()
        for socket, p in power.items():
            energy_wh = p * (duration_sec / 3600.0)
            self.energy_log[socket] = self.energy_log.get(socket, 0.0) + energy_wh

    def export_telemetry(self) -> Dict:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "pdu_id": self.id,
            "power_watts": self.compute_power(),
            "energy_wh": self.energy_log
        }

# Simulate the telemetry agent
if __name__ == "__main__":
    voltage_zones = {"1-12": 230.0, "13-24": 230.0}
    pdu = PDU("PDU-001", voltage_zones)

    # Simulate a current snapshot (in Amps)
    sample_currents = {i: 0.3 for i in range(1, 25)}
    pdu.update_currents(sample_currents)

    # Simulate time passing
    pdu.update_energy(duration_sec=60)

    # Get telemetry data
    print(pdu.export_telemetry())
