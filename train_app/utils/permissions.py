class PermissionNode:
    def __init__(self, name):
        self.name = name
        self.children = {}


class PermissionTree:
    def __init__(self):
        self.root = PermissionNode("Root")

    def add_permission(self, role, module, function):
        current = self.root
        for node in [role, module, function]:
            if node not in current.children:
                current.children[node] = PermissionNode(node)
            current = current.children[node]

    def check_permission(self, role, module, function):
        current = self.root
        for node in [role, module, function]:
            if node not in current.children:
                return False
            current = current.children[node]
        return True


perm_tree = PermissionTree()
perm_tree.add_permission("admin", "ticket_module", "query")
perm_tree.add_permission("admin", "train_module", "manage")
perm_tree.add_permission("admin", "user_module", "manage")
perm_tree.add_permission("user", "ticket_module", "query")
perm_tree.add_permission("user", "ticket_module", "book")
perm_tree.add_permission("user", "ticket_module", "refund")
perm_tree.add_permission("user", "ticket_module", "reschedule")
perm_tree.add_permission("user", "user_module", "info")

__all__ = ["PermissionNode", "PermissionTree", "perm_tree"]
