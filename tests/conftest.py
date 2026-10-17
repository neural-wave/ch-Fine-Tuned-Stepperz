"""Real model inference requires explicit opt-in, including in Test Explorer."""
import pytest
import logging

from agent_orchestration.logging_setup import configure_logging

logger = logging.getLogger("tests")


def pytest_report_header(config):
    return f"Log file: {configure_logging('pytest')}"


def pytest_sessionstart(session):
    path = configure_logging("pytest")
    logger.info("Pytest session started root=%s file=%s", session.config.rootpath, path)


def pytest_runtest_logreport(report):
    if report.failed:
        logger.error("Test failed node=%s phase=%s\n%s", report.nodeid, report.when, report.longrepr)
    else:
        logger.info("Test node=%s phase=%s outcome=%s duration=%.3fs properties=%r",
                    report.nodeid, report.when, report.outcome, report.duration, report.user_properties)


def pytest_sessionfinish(session, exitstatus):
    logger.info("Pytest session finished exit_status=%s", exitstatus)


def pytest_addoption(parser):
    parser.addoption("--run-model-health", action="store_true", default=False,
                     help="Load real models and run inference health checks")
    parser.addoption("--model-config", default="config/agents/models.json",
                     help="Model configuration used by real health checks")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-model-health"):
        skip = pytest.mark.skip(reason="Real inference disabled; use --run-model-health")
        for item in items:
            if item.get_closest_marker("model_health"):
                item.add_marker(skip)
