import unittest

try:
    import numpy as np
except ImportError:
    np = None

if np is not None:
    from bitcoin_events import derivatives, independent_peaks, split_at


@unittest.skipIf(np is None, "Análise de eventos requer requirements-analysis.txt no ambiente .venv")
class DerivativeTests(unittest.TestCase):
    def test_exponential_curve_has_constant_log_velocity(self):
        t = np.arange(100, dtype=float)
        velocity, acceleration = derivatives((t * 60).astype(np.int64), 100 * np.exp(.002 * t), 5)
        np.testing.assert_allclose(velocity[5:], .2, atol=1e-12)
        np.testing.assert_allclose(acceleration[10:], 0, atol=1e-12)
        self.assertTrue(np.all(np.isnan(velocity[:5])))

    def test_quadratic_log_curve_has_known_acceleration(self):
        t = np.arange(50, dtype=float)
        _, acceleration = derivatives((t * 60).astype(np.int64), np.exp(.0001 * t**2), 3)
        np.testing.assert_allclose(acceleration[6:], .02, atol=1e-12)

    def test_no_derivative_crosses_gap(self):
        times = np.arange(12, dtype=np.int64) * 60
        times[5:] += 60
        velocity, acceleration = derivatives(times, np.arange(12) + 100., 2)
        self.assertTrue(np.all(np.isnan(velocity[5:7])))
        self.assertTrue(np.all(np.isnan(acceleration[5:9])))
        self.assertTrue(np.isfinite(velocity[7]))
        self.assertTrue(np.isfinite(acceleration[9]))

    def test_future_does_not_alter_past_derivatives(self):
        times = np.arange(100, dtype=np.int64) * 60
        prices = 100 + np.sin(np.arange(100))
        full = derivatives(times, prices, 5)
        prefix = derivatives(times[:60], prices[:60], 5)
        for left, right in zip(full, prefix):
            np.testing.assert_allclose(left[:60], right, equal_nan=True)

    def test_independent_peaks_keep_strongest_and_separate_episodes(self):
        times = np.array([0, 100, 90_000, 180_000])
        self.assertEqual(independent_peaks([1, 0, 2, 3], times, count=3, separation_hours=24), [1, 2, 3])

    def test_invalid_prices_and_duplicate_times(self):
        for prices in (np.array([1., 0.]), np.array([1., np.nan])):
            with self.assertRaises(ValueError):
                derivatives(np.array([0, 60]), prices, 1)
        with self.assertRaises(ValueError):
            derivatives(np.array([0, 0]), np.array([1., 2.]), 1)

    def test_split_at_shared_boundary_uses_ending_window(self):
        boundaries = {"train": {"first_start_utc": "2020-01-01T00:00:00Z", "last_available_at_utc": "2020-01-02T00:00:00Z"},
                      "validation": {"first_start_utc": "2020-01-02T00:00:00Z", "last_available_at_utc": "2020-01-03T00:00:00Z"}}
        self.assertEqual(split_at("2020-01-02T00:00:00Z", boundaries), "train")


if __name__ == "__main__":
    unittest.main()
