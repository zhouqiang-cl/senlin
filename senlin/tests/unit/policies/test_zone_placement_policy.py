# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from senlin.drivers import base as driver_base
from senlin.engine import cluster as cluster_mod
from senlin.policies import base as policy_base
from senlin.policies import zone_placement as zp
from senlin.tests.unit.common import base
from senlin.tests.unit.common import utils


class TestZonePlacementPolicy(base.SenlinTestCase):

    def setUp(self):
        super(TestZonePlacementPolicy, self).setUp()
        self.context = utils.dummy_context()
        self.spec = {
            'type': 'senlin.policy.zone_placement',
            'version': '1.0',
            'properties': {
                'zones': [
                    {'name': 'AZ1', 'weight': 100},
                    {'name': 'AZ2', 'weight': 80},
                    {'name': 'AZ3', 'weight': 60},
                    {'name': 'AZ4', 'weight': 40}
                ]
            }
        }

    def test_policy_init(self):
        policy = zp.ZonePlacementPolicy('test-policy', self.spec)

        self.assertIsNone(policy.id)
        self.assertEqual('test-policy', policy.name)
        self.assertEqual('senlin.policy.zone_placement-1.0', policy.type)
        expected = {'AZ1': 100, 'AZ2': 80, 'AZ3': 60, 'AZ4': 40}
        self.assertEqual(expected, policy.zones)
        self.assertIsNone(policy. _novaclient)

    @mock.patch.object(policy_base.Policy, '_build_conn_params')
    @mock.patch.object(driver_base, 'SenlinDriver')
    def test__nova(self, mock_driver, mock_conn):
        params = mock.Mock()
        mock_conn.return_value = params

        nc = mock.Mock()
        driver = mock.Mock()
        driver.compute.return_value = nc
        mock_driver.return_value = driver

        cluster = mock.Mock()
        policy = zp.ZonePlacementPolicy('p1', self.spec)

        res = policy._nova(cluster)

        self.assertEqual(nc, res)
        self.assertEqual(nc, policy._novaclient)
        mock_conn.assert_called_once_with(cluster)
        mock_driver.assert_called_once_with()
        driver.compute.assert_called_once_with(params)

    def test__create_plan_default(self):
        self.spec['properties']['zones'] = [
            {'name': 'AZ1'}, {'name': 'AZ2'}, {'name': 'AZ3'}, {'name': 'AZ4'}
        ]
        policy = zp.ZonePlacementPolicy('test-policy', self.spec)
        zones = policy.zones

        current = {'AZ1': 2, 'AZ2': 2, 'AZ3': 2, 'AZ4': 1}
        plan = policy._create_plan(current, zones, 5, True)
        answer = {'AZ1': 1, 'AZ2': 1, 'AZ3': 1, 'AZ4': 2}
        self.assertEqual(answer, plan)

    def test__create_plan(self):
        policy = zp.ZonePlacementPolicy('test-policy', self.spec)
        zones = policy.zones

        current = {'AZ1': 2, 'AZ2': 2, 'AZ3': 2, 'AZ4': 1}
        plan = policy._create_plan(current, zones, 7, True)
        answer = {'AZ1': 3, 'AZ2': 2, 'AZ3': 1, 'AZ4': 1}
        self.assertEqual(answer, plan)

        current = {'AZ1': 2, 'AZ2': 4, 'AZ3': 2, 'AZ4': 2}
        plan = policy._create_plan(current, zones, 6, True)
        answer = {'AZ1': 4, 'AZ2': 1, 'AZ3': 1}
        self.assertEqual(answer, plan)

        current = {'AZ1': 4, 'AZ2': 5, 'AZ3': 1, 'AZ4': 1}
        plan = policy._create_plan(current, zones, 3, False)
        answer = {'AZ2': 3}
        self.assertEqual(answer, plan)

        current = {'AZ1': 6, 'AZ2': 2, 'AZ3': 4, 'AZ4': 6}
        plan = policy._create_plan(current, zones, 4, False)
        answer = {'AZ4': 4}
        self.assertEqual(answer, plan)

    @mock.patch.object(zp.ZonePlacementPolicy, '_nova')
    @mock.patch.object(cluster_mod.Cluster, 'load')
    def test_pre_op_expand_using_input(self, mock_load, mock_nova):
        policy = zp.ZonePlacementPolicy('test-policy', self.spec)
        zones = policy.zones

        nc = mock.Mock()
        nc.validate_azs.return_value = zones.keys()
        mock_nova.return_value = nc

        action = mock.Mock()
        action.action = 'CLUSTER_SCALE_OUT'
        action.context = self.context
        action.data = {}
        action.inputs = {'count': 7}

        cluster = mock.Mock()
        current_dist = {'AZ1': 2, 'AZ2': 3, 'AZ3': 2, 'AZ4': 1}
        cluster.get_zone_distribution.return_value = current_dist
        mock_load.return_value = cluster

        policy.pre_op('FAKE_CLUSTER', action)

        self.assertEqual(7, action.data['creation']['count'])
        dist = action.data['creation']['zones']
        self.assertEqual(4, dist['AZ1'])
        self.assertEqual(2, dist['AZ2'])
        self.assertEqual(1, dist['AZ3'])

        mock_load.assert_called_once_with(action.context, 'FAKE_CLUSTER')
        mock_nova.assert_called_once_with(cluster)
        nc.validate_azs.assert_called_once_with(zones.keys())
        cluster.get_zone_distribution.assert_called_once_with(
            action.context, zones.keys())

    @mock.patch.object(zp.ZonePlacementPolicy, '_nova')
    @mock.patch.object(cluster_mod.Cluster, 'load')
    def test_pre_op_shrink_using_data(self, mock_load, mock_nova):
        policy = zp.ZonePlacementPolicy('test-policy', self.spec)
        zones = policy.zones

        nc = mock.Mock()
        nc.validate_azs.return_value = zones.keys()
        mock_nova.return_value = nc

        action = mock.Mock()
        action.action = 'CLUSTER_SCALE_IN'
        action.context = self.context
        action.data = {'deletion': {'count': 2}}
        action.inputs = {}

        cluster = mock.Mock()
        current_dist = {'AZ1': 2, 'AZ2': 2, 'AZ3': 2, 'AZ4': 1}
        cluster.get_zone_distribution.return_value = current_dist
        mock_load.return_value = cluster

        policy.pre_op('FAKE_CLUSTER', action)

        self.assertEqual(2, action.data['deletion']['count'])
        dist = action.data['deletion']['zones']
        self.assertEqual(1, dist['AZ3'])
        self.assertEqual(1, dist['AZ4'])

        mock_load.assert_called_once_with(action.context, 'FAKE_CLUSTER')
        mock_nova.assert_called_once_with(cluster)
        nc.validate_azs.assert_called_once_with(zones.keys())
        cluster.get_zone_distribution.assert_called_once_with(
            action.context, zones.keys())

    @mock.patch.object(zp.ZonePlacementPolicy, '_nova')
    @mock.patch.object(cluster_mod.Cluster, 'load')
    def test_pre_op_no_zones(self, mock_load, mock_nova):
        policy = zp.ZonePlacementPolicy('p1', self.spec)
        nc = mock.Mock()
        nc.validate_azs.return_value = []
        mock_nova.return_value = nc

        action = mock.Mock()
        action.action = 'CLUSTER_SCALE_OUT'
        action.context = self.context
        action.data = {'creation': {'count': 3}}

        cluster = mock.Mock()
        mock_load.return_value = cluster

        res = policy.pre_op('FAKE_CLUSTER', action)

        self.assertIsNone(res)
        self.assertEqual('ERROR', action.data['status'])
        self.assertEqual('No availability zone found available.',
                         action.data['reason'])

    @mock.patch.object(zp.ZonePlacementPolicy, '_nova')
    @mock.patch.object(cluster_mod.Cluster, 'load')
    def test_pre_op_no_feasible_plan(self, mock_load, mock_nova):
        policy = zp.ZonePlacementPolicy('p1', self.spec)
        zones = policy.zones

        nc = mock.Mock()
        nc.validate_azs.return_value = zones.keys()
        mock_nova.return_value = nc

        self.patchobject(policy, '_create_plan', return_value=None)

        action = mock.Mock()
        action.action = 'CLUSTER_SCALE_OUT'
        action.context = self.context
        action.inputs = {}
        action.data = {'creation': {'count': 3}}

        cluster = mock.Mock()
        current_dist = {'R1': 0, 'R2': 0, 'R3': 0, 'R4': 0}
        cluster.get_zone_distribution.return_value = current_dist
        mock_load.return_value = cluster

        res = policy.pre_op('FAKE_CLUSTER', action)

        self.assertIsNone(res)

        self.assertEqual('ERROR', action.data['status'])
        self.assertEqual('There is no feasible plan to handle all nodes.',
                         action.data['reason'])

        mock_load.assert_called_once_with(action.context, 'FAKE_CLUSTER')
        nc.validate_azs.assert_called_once_with(zones.keys())
        cluster.get_zone_distribution.assert_called_once_with(
            action.context, zones.keys())
        policy._create_plan.assert_called_once_with(
            current_dist, zones, 3, True)
