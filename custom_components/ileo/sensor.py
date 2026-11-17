"""Capteurs Iléo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BASE_URL
from .const import DOMAIN, MANUFACTURER
from .coordinator import IleoConfigEntry, IleoCoordinator, IleoData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IleoSensorEntityDescription(SensorEntityDescription):
    """Description d'un capteur Iléo."""

    value_fn: Callable[[IleoData], StateType | date]


SENSORS: tuple[IleoSensorEntityDescription, ...] = (
    IleoSensorEntityDescription(
        key="index",
        translation_key="index",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=lambda data: data.latest_index,
    ),
    IleoSensorEntityDescription(
        key="last_day_consumption",
        translation_key="last_day_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value_fn=lambda data: data.last_day_consumption,
    ),
    IleoSensorEntityDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data.latest.day if data.latest else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IleoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Ajoute les capteurs d'une entrée Iléo."""
    coordinator = entry.runtime_data
    async_add_entities(IleoSensor(coordinator, description) for description in SENSORS)


class IleoSensor(CoordinatorEntity[IleoCoordinator], SensorEntity):
    """Capteur alimenté par le coordinateur Iléo."""

    _attr_has_entity_name = True
    entity_description: IleoSensorEntityDescription

    def __init__(
        self, coordinator: IleoCoordinator, description: IleoSensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Compteur d'eau Iléo",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )

    @property
    def native_value(self) -> StateType | date:
        return self.entity_description.value_fn(self.coordinator.data)
