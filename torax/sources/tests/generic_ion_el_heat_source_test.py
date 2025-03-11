# Copyright 2024 DeepMind Technologies Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from absl.testing import absltest
from torax.sources import generic_ion_el_heat_source
from torax.sources.tests import test_lib
import jax.numpy as jnp
import jax.scipy.integrate
from torax.core_profiles import initialization
from torax.geometry import pydantic_model as geometry_pydantic_model
from torax.config import build_runtime_params
from torax.config import runtime_params as general_runtime_params
from torax.config import runtime_params_slice
from torax.sources import source_models as source_models_lib
from torax.utils import math_utils


class GenericIonElectronHeatSourceTest(test_lib.IonElSourceTestCase):
  """Tests for GenericIonElectronHeatSource."""

  @classmethod
  def setUpClass(cls):
    super().setUpClass(
        source_class=generic_ion_el_heat_source.GenericIonElectronHeatSource,
        runtime_params_class=generic_ion_el_heat_source.RuntimeParams,
        source_name=generic_ion_el_heat_source.GenericIonElectronHeatSource.SOURCE_NAME,
        model_func=generic_ion_el_heat_source.default_formula,
    )

  def test_absorption_fraction(self):
    """Tests that absorption_fraction correctly affects power calculations."""
    # Create test geometry
    geo = geometry_pydantic_model.CircularConfig().build_geometry()
    
    # Test parameters
    rsource = 0.5
    w = 0.2
    Ptot = 1.0
    el_heat_fraction = 0.5
    
    # Calculate heat source with absorption_fraction = 1.0
    ion1, el1 = generic_ion_el_heat_source.calc_generic_heat_source(
        geo=geo,
        rsource=rsource,
        w=w,
        Ptot=Ptot,
        el_heat_fraction=el_heat_fraction,
        absorption_fraction=1.0,
    )
    
    # Calculate heat source with absorption_fraction = 0.5
    ion2, el2 = generic_ion_el_heat_source.calc_generic_heat_source(
        geo=geo,
        rsource=rsource,
        w=w,
        Ptot=Ptot,
        el_heat_fraction=el_heat_fraction,
        absorption_fraction=0.5,
    )
    
    # Integrate the power profiles
    integrated_ion1 = math_utils.volume_integration(ion1, geo)
    integrated_ion2 = math_utils.volume_integration(ion2, geo)
    integrated_el1 = math_utils.volume_integration(el1, geo)
    integrated_el2 = math_utils.volume_integration(el2, geo)
    
    # Test that the absorbed power is scaled by absorption_fraction
    # Profile 2 should have half the power of profile 1
    self.assertAlmostEqual(integrated_ion2 / integrated_ion1, 0.5, places=5)
    self.assertAlmostEqual(integrated_el2 / integrated_el1, 0.5, places=5)


if __name__ == '__main__':
  absltest.main()
