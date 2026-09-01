"""
Control-flow signal exceptions for cecli.

These signals are used for non-error control flow (like switching coders
or reloading the program). They inherit from BaseException to avoid being
caught by generic `except Exception` handlers.
"""


class SwitchCoderSignal(BaseException):
    """
     Signal to switch the current Coder instance to a new configuration.

     This is NOT an error - it's a control flow signal used to propagate
     coder switching requests up through the async call stack. It carries
     the kwargs needed to create a new Coder instance.

     Note: Inherits from BaseException (like KeyboardInterrupt and SystemExit)
    to avoid being caught by generic `except Exception` handlers, making the
     non-error nature of this signal explicit.

     Attributes:
         kwargs: Configuration dict passed to Coder.create() for the new instance
         placeholder: Optional placeholder text for the input prompt
    """

    def __init__(self, placeholder=None, **kwargs):
        self.kwargs = kwargs
        self.placeholder = placeholder
        super().__init__()


class ReloadProgramSignal(BaseException):
    """
    Signal to reload the entire program configuration.

    This is NOT an error - it's a control flow signal used to trigger
    a full program reload, re-parsing config files and re-initializing
    all components. Useful for hot-reloading when configuration files
    change.

    Note: Inherits from BaseException (like KeyboardInterrupt and SystemExit)
    to avoid being caught by generic `except Exception` handlers.
    """

    def __init__(self, message="Reloading program configuration...", **kwargs):
        self.kwargs = kwargs
        self.message = message
        super().__init__(self.message)
