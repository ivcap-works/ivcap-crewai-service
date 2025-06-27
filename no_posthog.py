import posthog

def noop(*args, **kwargs):
    pass

def no_posthog():
    # Patch the main event capture methods to do nothing
    posthog.capture = noop
    posthog.identify = noop
    posthog.alias = noop
    posthog.group = noop
    posthog.flush = noop
    posthog.shutdown = noop

    # Patch instance methods for all Posthog clients
    posthog.Posthog.capture = noop
    posthog.Posthog.identify = noop
    posthog.Posthog.alias = noop
    posthog.Posthog.group = noop
    posthog.Posthog.flush = noop
    posthog.Posthog.shutdown = noop

    # Just for good measure
    posthog.disabled = True
