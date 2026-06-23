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
