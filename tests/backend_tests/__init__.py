"""Module containing all CdEDB backend tests, one file per backend."""
from tests.backend_tests.assembly import TestAssemblyBackend as TestAssemblyBackend
from tests.backend_tests.cde import TestCdEBackend as TestCdEBackend
from tests.backend_tests.common import TestBackendCommon as TestBackendCommon
from tests.backend_tests.core import TestCoreBackend as TestCoreBackend
from tests.backend_tests.event import TestEventBackend as TestEventBackend
from tests.backend_tests.event_models import TestEventModels as TestEventModels
from tests.backend_tests.ml import TestMlBackend as TestMlBackend
from tests.backend_tests.past_event import TestPastEventBackend as TestPastEventBackend
