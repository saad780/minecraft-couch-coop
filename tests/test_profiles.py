import unittest
from mc_couch.profiles import selection_index


class SelectionTests(unittest.TestCase):
    def test_four_remembered_profiles_stay_selected_as_other_players_join(self):
        names = ["Player1", "Player2", "Player3", "Player4"]
        old = [names + ["New profile", "Leave session"] for _ in names]
        indices = list(range(4))
        used = []
        for seat, name in enumerate(names):
            self.assertEqual(old[seat][indices[seat]], name)
            used.append(name)
            for other in range(seat + 1, 4):
                current = [n for n in names if n not in used] + [
                    "New profile",
                    "Leave session",
                ]
                indices[other] = selection_index(old[other], current, indices[other])
                old[other] = current
                self.assertEqual(current[indices[other]], names[other])

    def test_leave_action_keeps_its_meaning_when_profiles_change(self):
        before = ["Player1", "Player2", "New profile", "Leave session"]
        after = ["Player2", "New profile", "Leave session"]
        self.assertEqual(after[selection_index(before, after, 3)], "Leave session")

    def test_claimed_profile_falls_back_to_first_available_profile(self):
        before = ["Player1", "Player2", "New profile", "Leave session"]
        after = ["Player1", "New profile", "Leave session"]
        self.assertEqual(after[selection_index(before, after, 1)], "Player1")


if __name__ == "__main__":
    unittest.main()
