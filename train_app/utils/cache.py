class O1HashCache:
    def __init__(self):
        self.usernames = set()
        self.id_nums = set()

    def load_data(self, users):
        for u in users:
            self.usernames.add(u.username)
            self.id_nums.add(u.id_num)

    def is_username_exist(self, username):
        return username in self.usernames

    def is_id_num_exist(self, id_num):
        return id_num in self.id_nums

    def add_user(self, username, id_num):
        self.usernames.add(username)
        self.id_nums.add(id_num)

    def update_username(self, old_name, new_name):
        if old_name in self.usernames:
            self.usernames.discard(old_name)
        self.usernames.add(new_name)

    def remove_user(self, username, id_num):
        self.usernames.discard(username)
        self.id_nums.discard(id_num)


user_cache = O1HashCache()

__all__ = ["O1HashCache", "user_cache"]
