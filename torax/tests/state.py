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

"""Unit tests for torax.state and torax.core_profile_setters."""

import dataclasses
import functools
from typing import Callable

from absl.testing import absltest
from absl.testing import parameterized
import jax
from jax import numpy as jnp
import numpy as np
from torax import core_profile_setters
from torax import state
from torax.config import config_args
from torax.config import profile_conditions as profile_conditions_lib
from torax.config import runtime_params as general_runtime_params
from torax.config import runtime_params_slice
from torax.geometry import geometry
from torax.geometry import geometry_provider
from torax.sources import source_models as source_models_lib
from torax.tests.test_lib import torax_refs


class StateTest(torax_refs.ReferenceValueTest):
  """Unit tests for the `torax.state` module."""

  def setUp(self):
    super().setUp()

    # Make a State object in history mode, output by scan
    self.history_length = 2
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()

    def make_hist(geo, dynamic_runtime_params_slice, static_slice):
      initial_counter = jnp.array(0)

      def scan_f(counter: jax.Array, _) -> tuple[jax.Array, state.CoreProfiles]:
        core_profiles = core_profile_setters.initial_core_profiles(
            dynamic_runtime_params_slice=dynamic_runtime_params_slice,
            static_runtime_params_slice=static_slice,
            geo=geo,
            source_models=source_models,
        )
        # Make one variable in the history track the value of the counter
        value = jnp.ones_like(core_profiles.temp_ion.value) * counter
        core_profiles = config_args.recursive_replace(
            core_profiles, temp_ion={'value': value}
        )
        return counter + 1, core_profiles.history_elem()

      _, history = jax.lax.scan(
          scan_f,
          initial_counter,
          xs=None,
          length=self.history_length,
      )
      return history

    def make_history(runtime_params, geo_provider):
      dynamic_runtime_params_slice, geo = (
          torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
              runtime_params,
              geo_provider,
              sources=source_models_builder.runtime_params,
          )
      )
      static_slice = runtime_params_slice.build_static_runtime_params_slice(
          runtime_params,
          source_runtime_params=source_models_builder.runtime_params,
      )
      # Bind non-JAX arguments so it can be jitted
      bound = functools.partial(
          make_hist,
          geo,
          dynamic_runtime_params_slice,
          static_slice,
      )
      return jax.jit(bound)()

    self._make_history = make_history

  @parameterized.parameters([
      dict(references_getter=torax_refs.circular_references),
      dict(references_getter=torax_refs.chease_references_Ip_from_chease),
      dict(
          references_getter=torax_refs.chease_references_Ip_from_runtime_params
      ),
  ])
  def test_sanity_check(
      self,
      references_getter: Callable[[], torax_refs.References],
  ):
    """Make sure State.sanity_check can be called."""
    references = references_getter()
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()
    dynamic_runtime_params_slice, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            references.runtime_params,
            references.geometry_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        references.runtime_params,
        source_runtime_params=source_models_builder.runtime_params,
    )
    basic_core_profiles = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dynamic_runtime_params_slice,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    basic_core_profiles.sanity_check()

  @parameterized.parameters([
      dict(references_getter=torax_refs.circular_references),
      dict(references_getter=torax_refs.chease_references_Ip_from_chease),
      dict(
          references_getter=torax_refs.chease_references_Ip_from_runtime_params
      ),
  ])
  def test_index(
      self,
      references_getter: Callable[[], torax_refs.References],
  ):
    """Test State.index."""
    references = references_getter()
    history = self._make_history(
        references.runtime_params, references.geometry_provider
    )

    for i in range(self.history_length):
      self.assertEqual(i, history.index(i).temp_ion.value[0])

  @parameterized.parameters([
      dict(references_getter=torax_refs.circular_references),
      dict(references_getter=torax_refs.chease_references_Ip_from_chease),
      dict(
          references_getter=torax_refs.chease_references_Ip_from_runtime_params
      ),
  ])
  def test_project(
      self,
      references_getter: Callable[[], torax_refs.References],
  ):
    """Test State.project."""
    references = references_getter()
    history = self._make_history(
        references.runtime_params, references.geometry_provider
    )

    seed = 20230421
    rng_state = jax.random.PRNGKey(seed)
    del seed  # Make sure seed isn't accidentally re-used
    weights = jax.random.normal(rng_state, (self.history_length,))
    del rng_state  # Make sure rng_state isn't accidentally re-used

    expected = jnp.dot(weights, jnp.arange(self.history_length))

    projected = history.project(weights)

    actual = projected.temp_ion.value[0]

    np.testing.assert_allclose(expected, actual)


class InitialStatesTest(parameterized.TestCase):
  """Unit tests for the `torax.core_profile_setters` module."""

  def test_initial_boundary_condition_from_time_dependent_params(self):
    """Tests that the initial boundary conditions are set from the config."""
    # Boundary conditions can be time-dependent, but when creating the initial
    # core profiles, we want to grab the boundary condition params at time 0.
    runtime_params = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            Ti_bound_right=27.7,
            Te_bound_right={0.0: 42.0, 1.0: 0.0},
            ne_bound_right=({0.0: 0.1, 1.0: 2.0}, 'step'),
            normalize_to_nbar=False,
        ),
    )
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()
    geo_provider = geometry_provider.ConstantGeometryProvider(
        geometry.build_circular_geometry()
    )
    dynamic_runtime_params_slice, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            runtime_params,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        runtime_params,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dynamic_runtime_params_slice,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    np.testing.assert_allclose(
        core_profiles.temp_ion.right_face_constraint, 27.7
    )
    np.testing.assert_allclose(
        core_profiles.temp_el.right_face_constraint, 42.0
    )
    np.testing.assert_allclose(core_profiles.ne.right_face_constraint, 0.1)

  def test_core_profiles_quasineutrality_check(self):
    """Tests core_profiles quasineutrality check on initial state."""
    runtime_params = general_runtime_params.GeneralRuntimeParams()
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()
    geo_provider = geometry_provider.ConstantGeometryProvider(
        geometry.build_circular_geometry()
    )
    dynamic_runtime_params_slice, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            runtime_params,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        runtime_params,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dynamic_runtime_params_slice,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    assert core_profiles.quasineutrality_satisfied()
    core_profiles = dataclasses.replace(
        core_profiles,
        Zi=core_profiles.Zi * 2.0,
    )
    assert not core_profiles.quasineutrality_satisfied()

  @parameterized.parameters([
      dict(geo_builder=geometry.build_circular_geometry),
      dict(
          geo_builder=lambda: geometry.build_standard_geometry(
              geometry.StandardGeometryIntermediates.from_chease()
          )
      ),
  ])
  def test_initial_psi_from_j(
      self,
      geo_builder: Callable[[], geometry.Geometry],
  ):
    """Tests expected behaviour of initial psi and current options."""
    config1 = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_j_is_total_current=True,
            initial_psi_from_j=True,
            nu=2,
            ne_bound_right=0.5,
        ),
    )
    config2 = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_j_is_total_current=False,
            initial_psi_from_j=True,
            nu=2,
            ne_bound_right=0.5,
        ),
    )
    config3 = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_j_is_total_current=False,
            initial_psi_from_j=True,
            nu=2,
            ne_bound_right=0.5,
        ),
    )
    # Needed to generate psi for bootstrap calculation
    config3_helper = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_j_is_total_current=True,
            initial_psi_from_j=True,
            nu=2,
            ne_bound_right=0.5,
        ),
    )
    geo_provider = geometry_provider.ConstantGeometryProvider(geo_builder())
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()
    source_models_builder.runtime_params['j_bootstrap'].bootstrap_mult = 0.0
    dcs1, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            config1,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config1,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles1 = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs1,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    source_models_builder.runtime_params['j_bootstrap'].bootstrap_mult = 0.0
    dcs2, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            config2,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config2,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles2 = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs2,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    source_models_builder.runtime_params['j_bootstrap'].bootstrap_mult = 1.0
    source_models_builder.runtime_params['generic_current_source'].fext = 0.0
    source_models = source_models_builder()
    dcs3, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            config3,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config3,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles3 = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs3,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )
    source_models_builder.runtime_params['j_bootstrap'].bootstrap_mult = 0.0
    source_models_builder.runtime_params['generic_current_source'].fext = 0.0
    dcs3_helper, geo = (
        torax_refs.build_consistent_dynamic_runtime_params_slice_and_geometry(
            config3_helper,
            geo_provider,
            sources=source_models_builder.runtime_params,
        )
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config3_helper,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles3_helper = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs3_helper,
        static_runtime_params_slice=static_slice,
        geo=geo,
        source_models=source_models,
    )

    # calculate total and Ohmic current profiles arising from nu=2
    jformula_face = (1 - geo.rho_face_norm**2) ** 2
    denom = jax.scipy.integrate.trapezoid(
        jformula_face * geo.spr_face, geo.rho_face_norm
    )
    ctot = config1.profile_conditions.Ip_tot * 1e6 / denom
    jtot_formula_face = jformula_face * ctot
    johm_formula_face = jtot_formula_face * (
        1 - dcs1.sources[source_models.generic_current_source_name].fext  # pytype: disable=attribute-error
    )

    # Calculate bootstrap current for config3 which doesn't zero it out
    source_models = source_models_lib.SourceModels()
    bootstrap_profile = source_models.j_bootstrap.get_value(
        dynamic_runtime_params_slice=dcs3,
        dynamic_source_runtime_params=dcs3.sources[
            source_models.j_bootstrap_name
        ],
        static_runtime_params_slice=static_slice,
        static_source_runtime_params=static_slice.sources[
            source_models.j_bootstrap_name
        ],
        geo=geo,
        core_profiles=core_profiles3_helper,
    )
    f_bootstrap = bootstrap_profile.I_bootstrap / (
        config3.profile_conditions.Ip_tot * 1e6
    )

    np.testing.assert_raises(
        AssertionError,
        np.testing.assert_allclose,
        core_profiles1.currents.jtot,
        core_profiles2.currents.jtot,
    )

    np.testing.assert_allclose(
        core_profiles1.currents.generic_current_source
        + core_profiles1.currents.johm,
        geometry.face_to_cell(jtot_formula_face),
        rtol=1e-12,
        atol=1e-12,
    )
    np.testing.assert_raises(
        AssertionError,
        np.testing.assert_allclose,
        core_profiles1.currents.johm,
        geometry.face_to_cell(johm_formula_face),
    )
    np.testing.assert_allclose(
        core_profiles2.currents.johm,
        geometry.face_to_cell(johm_formula_face),
        rtol=1e-12,
        atol=1e-12,
    )
    np.testing.assert_raises(
        AssertionError,
        np.testing.assert_allclose,
        core_profiles2.currents.jtot_face,
        jtot_formula_face,
    )
    np.testing.assert_allclose(
        core_profiles3.currents.johm,
        geometry.face_to_cell(jtot_formula_face) * (1 - f_bootstrap),
        rtol=1e-12,
        atol=1e-12,
    )

  def test_initial_psi_from_geo_noop_circular(self):
    """Tests expected behaviour of initial psi and current options."""
    source_models_builder = source_models_lib.SourceModelsBuilder()
    source_models = source_models_builder()
    config1 = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_psi_from_j=False,
            ne_bound_right=0.5,
        ),
    )
    geo = geometry.build_circular_geometry()
    dcs1 = runtime_params_slice.DynamicRuntimeParamsSliceProvider(
        config1,
        sources=source_models_builder.runtime_params,
        torax_mesh=geo.torax_mesh,
    )(
        t=config1.numerics.t_initial,
    )
    config2 = general_runtime_params.GeneralRuntimeParams(
        profile_conditions=profile_conditions_lib.ProfileConditions(
            initial_psi_from_j=True,
            ne_bound_right=0.5,
        ),
    )
    dcs2 = runtime_params_slice.DynamicRuntimeParamsSliceProvider(
        config2,
        sources=source_models_builder.runtime_params,
        torax_mesh=geo.torax_mesh,
    )(
        t=config2.numerics.t_initial,
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config1,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles1 = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs1,
        static_runtime_params_slice=static_slice,
        geo=geometry.build_circular_geometry(),
        source_models=source_models,
    )
    static_slice = runtime_params_slice.build_static_runtime_params_slice(
        config2,
        source_runtime_params=source_models_builder.runtime_params,
    )
    core_profiles2 = core_profile_setters.initial_core_profiles(
        dynamic_runtime_params_slice=dcs2,
        static_runtime_params_slice=static_slice,
        geo=geometry.build_circular_geometry(),
        source_models=source_models,
    )
    np.testing.assert_allclose(
        core_profiles1.currents.jtot, core_profiles2.currents.jtot
    )


if __name__ == '__main__':
  absltest.main()
