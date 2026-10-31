"""The Model Context Protocol Server implementation.

The MCP python sdk defines a Server API that provides the
MCP message handling logic and error handling.
"""

from collections.abc import Callable, Sequence
import json
import logging
from typing import Any, cast

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from probatio import to_openapi
from pydantic import AnyUrl
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .const import STATELESS_LLM_API

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_RESOURCE_URI = "homeassistant://assist/context-snapshot"
SNAPSHOT_RESOURCE_URL = AnyUrl(SNAPSHOT_RESOURCE_URI)
SNAPSHOT_RESOURCE_MIME_TYPE = "text/plain"
LIVE_CONTEXT_TOOL_NAME = "homeassistant__GetLiveContext"

# Additional climate MCP tools
CLIMATE_FAN_MODE_TOOL = "climate__HassClimateSetFanMode"
CLIMATE_HVAC_MODE_TOOL = "climate__HassClimateSetHvacMode"
CLIMATE_SWING_MODE_TOOL = "climate__HassClimateSetSwingMode"
CLIMATE_PRESET_MODE_TOOL = "climate__HassClimateSetPresetMode"

# Additional fan MCP tools
FAN_OSCILLATE_TOOL = "fan__HassFanSetOscillating"
FAN_DIRECTION_TOOL = "fan__HassFanSetDirection"


def _has_live_context_tool(llm_api: llm.APIInstance) -> bool:
    """Return if the selected API exposes the live context tool."""
    return any(tool.name == LIVE_CONTEXT_TOOL_NAME for tool in llm_api.tools)


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> types.Tool:
    """Format tool specification."""
    input_schema = to_openapi(tool.parameters, custom_serializer=custom_serializer)
    return types.Tool(
        name=tool.name,
        description=tool.description or "",
        inputSchema={
            "type": "object",
            "properties": input_schema["properties"],
        },
    )


def _get_custom_climate_tools() -> list[types.Tool]:
    """Return additional climate tools."""

    target_properties = {
        "name": {
            "type": "string",
            "description": (
                "Name of the climate device, for example: Điều hoà phòng khách."
            ),
        },
        "area": {
            "type": "string",
            "description": "Room or area name, for example: phòng khách.",
        },
        "floor": {
            "type": "string",
            "description": "Floor name, if specified.",
        },
        "preferred_area_id": {
            "type": "string",
            "description": "Preferred area ID, if available.",
        },
        "preferred_floor_id": {
            "type": "string",
            "description": "Preferred floor ID, if available.",
        },
    }

    return [
        types.Tool(
            name=CLIMATE_FAN_MODE_TOOL,
            description=(
                "Set the fan speed of a Home Assistant climate device. "
                "Find the device automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "For example, use name='Điều hoà phòng khách' and "
                "fan_mode='low'. Supported values depend on the device."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "fan_mode": {
                        "type": "string",
                        "description": (
                            "Fan speed to set, for example: auto, low, medium, high, mute, turbo."
                        ),
                    },
                },
                "required": ["fan_mode"],
            },
        ),
        types.Tool(
            name=CLIMATE_HVAC_MODE_TOOL,
            description=(
                "Change the operating mode of a Home Assistant climate device. "
                "Find the device automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "For example, use name='Điều hoà phòng khách' and "
                "hvac_mode='cool'. Supported values depend on the device."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "hvac_mode": {
                        "type": "string",
                        "description": (
                            "Operating mode: off, heat_cool, cool, heat, "
                            "fan_only or dry."
                        ),
                    },
                },
                "required": ["hvac_mode"],
            },
        ),
        types.Tool(
            name=CLIMATE_SWING_MODE_TOOL,
            description=(
                "Set the swing mode of a Home Assistant climate device. "
                "Find the device automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "For example, use name='Điều hoà phòng khách' and "
                "swing_mode='vertical'. Supported values: "
                "off, both, vertical and horizontal."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "swing_mode": {
                        "type": "string",
                        "description": (
                            "Swing mode: off, both, vertical or horizontal."
                        ),
                    },
                },
                "required": ["swing_mode"],
            },
        ),
        types.Tool(
            name=CLIMATE_PRESET_MODE_TOOL,
            description=(
                "Set the preset mode of a Home Assistant climate device. "
                "Find the device automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "Supported preset modes: none, sleep, Clean, Health, Antifungus. "
                "For example, use name='Điều hoà phòng khách' "
                "and preset_mode='sleep'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "preset_mode": {
                        "type": "string",
                        "enum": [
                            "none",
                            "sleep",
                            "Clean",
                            "Health",
                            "Antifungus",
                        ],
                        "description": (
                            "Preset mode: none, sleep, Clean, Health or Antifungus."
                        ),
                    },
                },
                "required": ["preset_mode"],
            },
        ),        
    ]


def _get_custom_fan_tools() -> list[types.Tool]:
    """Return additional fan tools."""

    target_properties = {
        "name": {
            "type": "string",
            "description": (
                "Name of the fan device, for example: "
                "Panasonic Living Fan."
            ),
        },
        "area": {
            "type": "string",
            "description": "Room or area name, for example: phòng khách.",
        },
        "floor": {
            "type": "string",
            "description": "Floor name, if specified.",
        },
        "preferred_area_id": {
            "type": "string",
            "description": "Preferred area ID, if available.",
        },
        "preferred_floor_id": {
            "type": "string",
            "description": "Preferred floor ID, if available.",
        },
    }

    return [
        types.Tool(
            name=FAN_OSCILLATE_TOOL,
            description=(
                "Turn fan oscillation on or off. "
                "Find the fan automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "Use oscillating=true to turn on oscillation, "
                "or oscillating=false to turn it off. "
                "For example, use name='Panasonic Living Fan' "
                "and oscillating=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "oscillating": {
                        "type": "boolean",
                        "description": (
                            "True to enable fan oscillation, "
                            "false to disable fan oscillation."
                        ),
                    },
                },
                "required": ["oscillating"],
            },
        ),
        types.Tool(
            name=FAN_DIRECTION_TOOL,
            description=(
                "Set the direction of a Home Assistant fan. "
                "Find the fan automatically using its name, area or floor. "
                "Do not provide entity_id. "
                "Use direction='forward' for forward airflow "
                "or direction='reverse' for reverse airflow. "
                "For example, use name='Panasonic Living Fan' "
                "and direction='reverse'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **target_properties,
                    "direction": {
                        "type": "string",
                        "enum": ["forward", "reverse"],
                        "description": (
                            "Fan direction: forward or reverse."
                        ),
                    },
                },
                "required": ["direction"],
            },
        ),
    ]


async def _call_custom_climate_tool(
    hass: HomeAssistant,
    llm_context: llm.LLMContext,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Handle climate tools using Home Assistant target matching."""

    from homeassistant.components.climate import ClimateEntityFeature
    from homeassistant.helpers import intent

    if name == CLIMATE_FAN_MODE_TOOL:
        mode_type = "fan_mode"
        requested_mode = arguments.get("fan_mode")
        required_feature = ClimateEntityFeature.FAN_MODE

    elif name == CLIMATE_HVAC_MODE_TOOL:
        mode_type = "hvac_mode"
        requested_mode = arguments.get("hvac_mode")
        required_feature = None

    elif name == CLIMATE_SWING_MODE_TOOL:
        mode_type = "swing_mode"
        requested_mode = arguments.get("swing_mode")
        required_feature = ClimateEntityFeature.SWING_MODE
        
    elif name == CLIMATE_PRESET_MODE_TOOL:
        mode_type = "preset_mode"
        requested_mode = arguments.get("preset_mode")
        required_feature = ClimateEntityFeature.PRESET_MODE        

    else:
        raise HomeAssistantError(f"Unknown climate tool: {name}")

    if not isinstance(requested_mode, str) or not requested_mode.strip():
        raise HomeAssistantError(f"Missing or invalid {mode_type}.")

    # Get target information from Xiaozhi.
    entity_name = arguments.get("name")
    area_name = arguments.get("area")
    floor_name = arguments.get("floor")

    # Match the climate device using Home Assistant Assist.
    match_constraints = intent.MatchTargetsConstraints(
        name=entity_name,
        area_name=area_name,
        floor_name=floor_name,
        domains=["climate"],
        assistant=llm_context.assistant,
        features=required_feature,
        single_target=True,
    )

    match_preferences = intent.MatchTargetsPreferences(
        area_id=arguments.get("preferred_area_id"),
        floor_id=arguments.get("preferred_floor_id"),
    )

    match_result = intent.async_match_targets(
        hass,
        match_constraints,
        match_preferences,
    )

    if not match_result.is_match or not match_result.states:
        raise HomeAssistantError(
            "Could not find a matching climate device. "
            f"Name: {entity_name}, area: {area_name}, floor: {floor_name}. "
            f"Reason: {match_result.no_match_reason}"
        )

    climate_state = match_result.states[0]
    entity_id = climate_state.entity_id

    # Validate the requested mode against the climate entity.
    attribute_name = {
        "fan_mode": "fan_modes",
        "hvac_mode": "hvac_modes",
        "swing_mode": "swing_modes",
        "preset_mode": "preset_modes",
    }[mode_type]

    available_modes = climate_state.attributes.get(attribute_name) or []

    resolved_mode = next(
        (
            mode
            for mode in available_modes
            if isinstance(mode, str)
            and mode.casefold() == requested_mode.strip().casefold()
        ),
        None,
    )

    if resolved_mode is None:
        raise HomeAssistantError(
            f"Unsupported {mode_type}: {requested_mode}. "
            f"Available modes: {available_modes}"
        )

    # Call the corresponding Home Assistant climate service.
    service = {
        "fan_mode": "set_fan_mode",
        "hvac_mode": "set_hvac_mode",
        "swing_mode": "set_swing_mode",
        "preset_mode": "set_preset_mode",
    }[mode_type]

    await hass.services.async_call(
        "climate",
        service,
        {
            mode_type: resolved_mode,
        },
        target={
            "entity_id": entity_id,
        },
        blocking=True,
    )

    _LOGGER.info(
        "Climate tool successful: %s, entity=%s, %s=%s",
        name,
        entity_id,
        mode_type,
        resolved_mode,
    )

    return {
        "success": True,
        "result": (
            f"{climate_state.name}: {mode_type} set to {resolved_mode}"
        ),
    }


async def _call_custom_fan_tool(
    hass: HomeAssistant,
    llm_context: llm.LLMContext,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Handle fan tools using Home Assistant target matching."""

    from homeassistant.components.fan import FanEntityFeature
    from homeassistant.helpers import intent

    # Determine which fan feature is being controlled.
    if name == FAN_OSCILLATE_TOOL:
        feature_type = "oscillate"
        requested_value = arguments.get("oscillating")

    elif name == FAN_DIRECTION_TOOL:
        feature_type = "direction"
        requested_value = arguments.get("direction")

    else:
        raise HomeAssistantError(f"Unknown fan tool: {name}")

    # Validate requested value.
    if feature_type == "oscillate":
        if not isinstance(requested_value, bool):
            raise HomeAssistantError(
                "Missing or invalid oscillating value. "
                "Expected true or false."
            )

        required_feature = FanEntityFeature.OSCILLATE

    else:
        if requested_value not in ("forward", "reverse"):
            raise HomeAssistantError(
                "Missing or invalid direction. "
                "Expected forward or reverse."
            )

        required_feature = FanEntityFeature.DIRECTION

    # Get target information from Xiaozhi.
    entity_name = arguments.get("name")
    area_name = arguments.get("area")
    floor_name = arguments.get("floor")

    # Match fan by name, area or floor.
    # Do not filter by features during target matching.
    match_constraints = intent.MatchTargetsConstraints(
        name=entity_name,
        area_name=area_name,
        floor_name=floor_name,
        domains=["fan"],
        assistant=llm_context.assistant,
        single_target=True,
    )

    match_preferences = intent.MatchTargetsPreferences(
        area_id=arguments.get("preferred_area_id"),
        floor_id=arguments.get("preferred_floor_id"),
    )

    match_result = intent.async_match_targets(
        hass,
        match_constraints,
        match_preferences,
    )

    if not match_result.is_match or not match_result.states:
        raise HomeAssistantError(
            "Could not find a matching fan device. "
            f"Name: {entity_name}, area: {area_name}, "
            f"floor: {floor_name}. "
            f"Reason: {match_result.no_match_reason}"
        )

    fan_state = match_result.states[0]
    entity_id = fan_state.entity_id

    # Verify that the selected fan supports the requested feature.
    supported_features = fan_state.attributes.get(
        "supported_features", 0
    )

    if not supported_features & required_feature:
        raise HomeAssistantError(
            f"Fan {entity_id} does not support {feature_type}."
        )

    # Call the corresponding Home Assistant fan service.
    if feature_type == "oscillate":
        await hass.services.async_call(
            "fan",
            "oscillate",
            {
                "oscillating": requested_value,
            },
            target={
                "entity_id": entity_id,
            },
            blocking=True,
        )

        result_text = (
            f"{fan_state.name}: oscillation "
            f"{'enabled' if requested_value else 'disabled'}"
        )

        _LOGGER.info(
            "Fan oscillation successful: entity=%s, oscillating=%s",
            entity_id,
            requested_value,
        )

    else:
        await hass.services.async_call(
            "fan",
            "set_direction",
            {
                "direction": requested_value,
            },
            target={
                "entity_id": entity_id,
            },
            blocking=True,
        )

        result_text = (
            f"{fan_state.name}: direction set to {requested_value}"
        )

        _LOGGER.info(
            "Fan direction successful: entity=%s, direction=%s",
            entity_id,
            requested_value,
        )

    return {
        "success": True,
        "result": result_text,
    }


async def create_server(
    hass: HomeAssistant,
    llm_api_id: str | list[str],
    llm_context: llm.LLMContext,
) -> Server:
    """Create a new Model Context Protocol Server.

    A Model Context Protocol Server object is associated with a single session.
    The MCP SDK handles the details of the protocol.
    """

    if llm_api_id == STATELESS_LLM_API:
        llm_api_id = llm.LLM_API_ASSIST

    server = Server[Any]("home-assistant")

    async def get_api_instance() -> llm.APIInstance:
        """Get the LLM API selected."""
        # Backwards compatibility with old MCP Server config
        return await llm.async_get_api(hass, llm_api_id, llm_context)

    @server.list_prompts()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_prompts() -> list[types.Prompt]:
        llm_api = await get_api_instance()
        return [
            types.Prompt(
                name=llm_api.api.name,
                description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            )
        ]

    @server.get_prompt()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        llm_api = await get_api_instance()
        if name != llm_api.api.name:
            raise ValueError(f"Unknown prompt: {name}")

        return types.GetPromptResult(
            description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(
                        type="text",
                        text=llm_api.api_prompt,
                    ),
                )
            ],
        )

    @server.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_list_resources() -> list[types.Resource]:
        llm_api = await get_api_instance()
        if not _has_live_context_tool(llm_api):
            return []

        return [
            types.Resource(
                uri=SNAPSHOT_RESOURCE_URL,
                name="assist_context_snapshot",
                title="Assist context snapshot",
                description=(
                    "A snapshot of the current Assist context, matching the"
                    " existing homeassistant__GetLiveContext tool output."
                ),
                mimeType=SNAPSHOT_RESOURCE_MIME_TYPE,
            )
        ]

    @server.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def handle_read_resource(
        uri: AnyUrl,
    ) -> Sequence[ReadResourceContents]:
        if str(uri) != SNAPSHOT_RESOURCE_URI:
            raise ValueError(f"Unknown resource: {uri}")

        llm_api = await get_api_instance()
        if not _has_live_context_tool(llm_api):
            raise ValueError(f"Unknown resource: {uri}")

        tool_response = await llm_api.async_call_tool(
            llm.ToolInput(
                tool_name=LIVE_CONTEXT_TOOL_NAME,
                tool_args={},
            )
        )

        if not tool_response.get("success"):
            raise HomeAssistantError(cast(str, tool_response["error"]))

        return [
            ReadResourceContents(
                content=cast(str, tool_response["result"]),
                mime_type=SNAPSHOT_RESOURCE_MIME_TYPE,
            )
        ]

    @server.list_tools()  # type: ignore[no-untyped-call]
    async def list_tools() -> list[types.Tool]:
        """List original tools and additional climate/fan tools."""
        llm_api = await get_api_instance()

        original_tools = [
            _format_tool(tool, llm_api.custom_serializer)
            for tool in llm_api.tools
        ]

        return (
            original_tools
            + _get_custom_climate_tools()
            + _get_custom_fan_tools()
        )

    @server.call_tool()  # type: ignore[no-untyped-decorator]
    async def call_tool(
        name: str,
        arguments: dict,
    ) -> Sequence[types.TextContent]:
        """Handle calling tools."""

        llm_api = await get_api_instance()

        _LOGGER.debug(
            "MCP Tool call: %s(%s)",
            name,
            arguments,
        )

        try:
            # Handle additional climate tools.
            if name in (
                CLIMATE_FAN_MODE_TOOL,
                CLIMATE_HVAC_MODE_TOOL,
                CLIMATE_SWING_MODE_TOOL,
                CLIMATE_PRESET_MODE_TOOL,
            ):
                tool_response = await _call_custom_climate_tool(
                    hass,
                    llm_context,
                    name,
                    arguments,
                )

            # Handle additional fan tools.
            elif name in (
                FAN_OSCILLATE_TOOL,
                FAN_DIRECTION_TOOL,
            ):
                tool_response = await _call_custom_fan_tool(
                    hass,
                    llm_context,
                    name,
                    arguments,
                )

            # All original Home Assistant tools use the original handler.
            else:
                tool_input = llm.ToolInput(
                    tool_name=name,
                    tool_args=arguments,
                )

                tool_response = await llm_api.async_call_tool(tool_input)

        except (HomeAssistantError, vol.Invalid) as e:
            _LOGGER.error(
                "Error calling MCP tool %s: %s",
                name,
                e,
            )
            raise HomeAssistantError(f"Error calling tool: {e}") from e

        return [
            types.TextContent(
                type="text",
                text=json.dumps(tool_response, ensure_ascii=False),
            )
        ]

    return server