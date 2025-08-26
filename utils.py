

# Proxying the Posthog client as it messes with our provenance tracking
#
from posthog import Posthog

class PosthogProxy:
    def capture(self, id,  event_name,  *args, **kwargs):
        pass

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def __setattr__(self, name, value):
        setattr(self._obj, name, value)

def posthog_new(cls, *args, **kwargs):
    return PosthogProxy()

Posthog.__new__ = posthog_new