"""Frozen native capabilities for finite scenarios, independent of manual holds."""
import copy


def validate(settings):
    if (type(settings) is not dict or 'nativeBindings' not in settings or
            set(settings) - {'nativeBindings', 'npcPersistence', 'morphSession'}):
        raise ValueError('native_session requires nativeBindings and only optional npcPersistence/morphSession')
    from .interactive_bindings import validate as validate_bindings
    result = copy.deepcopy(settings)
    result['nativeBindings'] = validate_bindings(settings['nativeBindings'])
    if result['nativeBindings'] is None:
        raise ValueError('native_session requires an enabled explicit nativeBindings policy')
    if 'npcPersistence' in settings and type(settings['npcPersistence']) is not bool:
        raise ValueError('npcPersistence requires an explicit boolean')
    if 'morphSession' in settings:
        from .morph_session import validate_config
        result['morphSession'] = validate_config(settings['morphSession'], result['nativeBindings'])
    return result


def settings(configuration):
    """Never fall back from a malformed/ambiguous finite policy to manual policy."""
    if 'native_session' in configuration:
        if 'interactive_session' in configuration:
            raise ValueError('native_session and interactive_session are mutually exclusive')
        return validate(configuration['native_session'])
    legacy = configuration.get('interactive_session', {})
    if type(legacy) is not dict:
        raise ValueError('interactive_session must be an explicit settings object')
    return legacy
