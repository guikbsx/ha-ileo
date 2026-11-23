"""Base entity of the Iléo integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BASE_URL
from .const import DOMAIN, MANUFACTURER
from .coordinator import IleoCoordinator


class IleoEntity(CoordinatorEntity[IleoCoordinator]):
    """Entity attached to the water meter of an Iléo contract."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IleoCoordinator, key: str) -> None:
        super().__init__(coordinator)
        contract = coordinator.contract
        self._attr_unique_id = f"{contract}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, contract)},
            translation_key="water_meter",
            manufacturer=MANUFACTURER,
            # The contract number tells the meters of several contracts apart.
            serial_number=contract,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )
