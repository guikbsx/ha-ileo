"""Sensors of the Iléo integration."""

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
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import IleoConfigEntry, IleoCoordinator, IleoData
from .entity import IleoEntity

# The coordinator does all the fetching: entities never query the portal.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IleoSensorEntityDescription(SensorEntityDescription):
    """Description of an Iléo sensor."""

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
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.latest.day if data.latest else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IleoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of an Iléo config entry."""
    coordinator = entry.runtime_data
    async_add_entities(IleoSensor(coordinator, description) for description in SENSORS)


class IleoSensor(IleoEntity, SensorEntity):
    """Sensor fed by the Iléo coordinator."""

    entity_description: IleoSensorEntityDescription

    def __init__(
        self, coordinator: IleoCoordinator, description: IleoSensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | date:
        return self.entity_description.value_fn(self.coordinator.data)
