import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from task_files import build_martyr_adn_map as builder


class MartyrAdnMapBuilderTestCase(unittest.TestCase):
    def test_resolve_google_api_key_returns_empty_string_when_missing(self):
        self.assertEqual(builder.resolve_google_api_key(''), '')

    def test_parse_google_duration_to_minutes(self):
        self.assertAlmostEqual(builder.parse_google_duration_to_minutes('165s'), 2.75)

    def test_build_google_candidate_routes_uses_cache_without_api_key(self):
        with TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / 'routes-cache.json'
            cache_key = builder.build_route_cache_key(21.0, 105.0, 21.1, 105.1, 'TRAFFIC_UNAWARE')
            builder.save_route_cache(
                cache_path,
                {
                    cache_key: {
                        'distance_km': 12.3,
                        'travel_minutes': 20.5,
                    }
                },
            )

            routes = builder.build_google_candidate_routes(
                areas=[
                    {'area_name': 'A', 'latitude': 21.0, 'longitude': 105.0},
                    {'area_name': 'B', 'latitude': 21.1, 'longitude': 105.1},
                ],
                nearest_candidates={0: [1]},
                api_key='',
                route_cache_path=cache_path,
                routing_preference='TRAFFIC_UNAWARE',
            )

            self.assertEqual(routes[(0, 1)]['distance_km'], 12.3)
            self.assertEqual(routes[(0, 1)]['travel_minutes'], 20.5)

    def test_build_google_candidate_routes_raises_clear_error_without_key_and_cache(self):
        with TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / 'routes-cache.json'

            with self.assertRaises(RuntimeError) as context:
                builder.build_google_candidate_routes(
                    areas=[
                        {'area_name': 'A', 'latitude': 21.0, 'longitude': 105.0},
                        {'area_name': 'B', 'latitude': 21.1, 'longitude': 105.1},
                    ],
                    nearest_candidates={0: [1]},
                    api_key='',
                    route_cache_path=cache_path,
                    routing_preference='TRAFFIC_UNAWARE',
                )

            self.assertIn('Thieu Google Maps API key', str(context.exception))

    def test_build_osrm_candidate_routes_uses_cache_without_server(self):
        with TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / 'routes-cache.json'
            cache_key = builder.build_route_cache_key(
                21.0,
                105.0,
                21.1,
                105.1,
                'driving',
                provider='osrm',
                provider_context='https://router.project-osrm.org',
            )
            builder.save_route_cache(
                cache_path,
                {
                    cache_key: {
                        'distance_km': 14.2,
                        'travel_minutes': 24.5,
                    }
                },
            )

            routes = builder.build_osrm_candidate_routes(
                areas=[
                    {'area_name': 'A', 'latitude': 21.0, 'longitude': 105.0},
                    {'area_name': 'B', 'latitude': 21.1, 'longitude': 105.1},
                ],
                nearest_candidates={0: [1]},
                route_cache_path=cache_path,
                base_url='https://router.project-osrm.org',
                profile='driving',
            )

            self.assertEqual(routes[(0, 1)]['distance_km'], 14.2)
            self.assertEqual(routes[(0, 1)]['travel_minutes'], 24.5)

    def test_resolve_routing_provider_prefers_osrm_without_keys(self):
        provider = builder.resolve_routing_provider(
            'auto',
            google_api_key='',
            vietmap_api_key='',
            allow_estimated_routes=False,
        )
        self.assertEqual(provider, 'osrm')

    def test_distance_priority_score_prefers_shorter_distance_when_loads_are_within_soft_band(self):
        shorter_score = builder.score_distance_priority_solution(
            load_values=[110, 230, 260, 380],
            distance_values=[18.0, 20.0, 24.0, 26.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
        )
        longer_score = builder.score_distance_priority_solution(
            load_values=[100, 210, 290, 380],
            distance_values=[24.0, 28.0, 31.0, 35.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
        )

        self.assertLess(shorter_score, longer_score)

    def test_distance_priority_score_penalizes_extreme_imbalance_before_distance(self):
        distance_only_option = builder.score_distance_priority_solution(
            load_values=[50, 60, 430, 440],
            distance_values=[12.0, 13.0, 14.0, 15.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
        )
        balanced_enough_option = builder.score_distance_priority_solution(
            load_values=[105, 220, 300, 355],
            distance_values=[16.0, 17.0, 18.0, 19.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
        )

        self.assertLess(balanced_enough_option, distance_only_option)

    def test_distance_priority_score_prefers_more_spread_out_sites_when_travel_is_equal(self):
        tighter_sites_score = builder.score_distance_priority_solution(
            load_values=[105, 220, 300, 355],
            distance_values=[16.0, 17.0, 18.0, 19.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
            site_min_spacing_km=18.0,
            site_average_spacing_km=34.0,
        )
        wider_sites_score = builder.score_distance_priority_solution(
            load_values=[105, 220, 300, 355],
            distance_values=[16.0, 17.0, 18.0, 19.0],
            average_load=245.0,
            preferred_load_min=98.0,
            preferred_load_max=420.0,
            site_min_spacing_km=42.0,
            site_average_spacing_km=66.0,
        )

        self.assertLess(wider_sites_score, tighter_sites_score)

    def test_distance_priority_assignments_keep_selected_sites_on_themselves(self):
        areas = [
            {'area_name': 'A', 'registrant_count': 100},
            {'area_name': 'B', 'registrant_count': 100},
            {'area_name': 'C', 'registrant_count': 60},
        ]
        candidate_routes = {
            (0, 0): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (0, 1): {'distance_km': 25.0, 'travel_minutes': 30.0},
            (1, 0): {'distance_km': 25.0, 'travel_minutes': 30.0},
            (1, 1): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (2, 0): {'distance_km': 6.0, 'travel_minutes': 8.0},
            (2, 1): {'distance_km': 8.0, 'travel_minutes': 10.0},
        }

        assignments, loads = builder.build_distance_capped_assignments(
            areas=areas,
            selected_sites=[0, 1],
            candidate_routes=candidate_routes,
            max_distance_km=100.0,
            preferred_load_min=50.0,
            soft_load_max=220.0,
        )

        self.assertIsNotNone(assignments)
        self.assertEqual(assignments[0], 0)
        self.assertEqual(assignments[1], 1)
        self.assertEqual(loads[0], 160)
        self.assertEqual(loads[1], 100)

    def test_distance_priority_assignments_limit_large_detours_from_nearest_site(self):
        areas = [
            {'area_name': 'A', 'registrant_count': 100},
            {'area_name': 'B', 'registrant_count': 100},
            {'area_name': 'C', 'registrant_count': 40},
        ]
        candidate_routes = {
            (0, 0): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (0, 1): {'distance_km': 40.0, 'travel_minutes': 48.0},
            (1, 0): {'distance_km': 40.0, 'travel_minutes': 48.0},
            (1, 1): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (2, 0): {'distance_km': 10.0, 'travel_minutes': 12.0},
            (2, 1): {'distance_km': 35.0, 'travel_minutes': 42.0},
        }

        assignments, _ = builder.build_distance_capped_assignments(
            areas=areas,
            selected_sites=[0, 1],
            candidate_routes=candidate_routes,
            max_distance_km=100.0,
            preferred_load_min=50.0,
            soft_load_max=120.0,
        )

        self.assertIsNotNone(assignments)
        self.assertEqual(assignments[2], 0)

    def test_distance_priority_assignments_allow_only_small_detours(self):
        areas = [
            {'area_name': 'A', 'registrant_count': 120},
            {'area_name': 'B', 'registrant_count': 80},
            {'area_name': 'C', 'registrant_count': 40},
        ]
        candidate_routes = {
            (0, 0): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (0, 1): {'distance_km': 20.0, 'travel_minutes': 24.0},
            (1, 0): {'distance_km': 20.0, 'travel_minutes': 24.0},
            (1, 1): {'distance_km': 0.0, 'travel_minutes': 0.0},
            (2, 0): {'distance_km': 10.0, 'travel_minutes': 12.0},
            (2, 1): {'distance_km': 14.9, 'travel_minutes': 18.0},
        }

        assignments, _ = builder.build_distance_capped_assignments(
            areas=areas,
            selected_sites=[0, 1],
            candidate_routes=candidate_routes,
            max_distance_km=100.0,
            preferred_load_min=50.0,
            soft_load_max=120.0,
        )

        self.assertIsNotNone(assignments)
        self.assertEqual(assignments[2], 1)

    @unittest.skipIf(builder.pulp is None, 'pulp is not installed in this test environment')
    def test_solve_balanced_sites_uses_google_route_distances(self):
        areas = [
            {'area_name': 'A', 'registrant_count': 100},
            {'area_name': 'B', 'registrant_count': 100},
            {'area_name': 'C', 'registrant_count': 100},
            {'area_name': 'D', 'registrant_count': 100},
        ]
        nearest_candidates = {
            0: [0, 1],
            1: [0, 1],
            2: [2, 3],
            3: [2, 3],
        }
        candidate_routes = {
            (0, 0): {'distance_km': 5.0, 'travel_minutes': 10.0},
            (0, 1): {'distance_km': 1.0, 'travel_minutes': 3.0},
            (1, 0): {'distance_km': 6.0, 'travel_minutes': 12.0},
            (1, 1): {'distance_km': 1.0, 'travel_minutes': 3.0},
            (2, 2): {'distance_km': 7.0, 'travel_minutes': 15.0},
            (2, 3): {'distance_km': 1.0, 'travel_minutes': 3.0},
            (3, 2): {'distance_km': 8.0, 'travel_minutes': 16.0},
            (3, 3): {'distance_km': 1.0, 'travel_minutes': 3.0},
        }

        selected_sites, assignments = builder.solve_balanced_sites(
            areas,
            nearest_candidates,
            candidate_routes,
            site_count=2,
            load_min=150,
            load_max=250,
        )

        self.assertEqual(selected_sites, [1, 3])
        self.assertEqual(assignments[0], 1)
        self.assertEqual(assignments[1], 1)
        self.assertEqual(assignments[2], 3)
        self.assertEqual(assignments[3], 3)


if __name__ == '__main__':
    unittest.main()
