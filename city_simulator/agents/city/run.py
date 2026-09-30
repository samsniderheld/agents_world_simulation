"""Entry point for a CITY run (agents/jobs.py calls run() on the job
thread). Blocking; everything it does is streamed through
agents/city/recorder.py."""


def run(stop_flag=None, **params):
    raise RuntimeError("CITY mode's world loop isn't installed yet.")
