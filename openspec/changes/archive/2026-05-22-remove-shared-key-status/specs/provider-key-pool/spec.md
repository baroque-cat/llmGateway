# provider-key-pool (delta)

## REMOVED Requirements

### Requirement: Gateway cache ignores shared_key_status config
**Reason**: The `shared_key_status` field is being removed from `ProviderConfig` entirely. The requirement that gateway cache not read this field becomes meaningless when the field no longer exists.

**Migration**: No action needed. Gateway cache already does not read `shared_key_status` since the transparent-proxy-gateway change. After the field is removed from the schema, there is nothing to ignore.
