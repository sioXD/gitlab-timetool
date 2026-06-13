class Workitem:
    type = None

    def __init__(self, title, id):
        self.parent = None
        self.title = title
        self.id = id
        self.hoursSpent = 0
        self.hoursEstimate = 0
        self.children = []

    def __eq__(self, other):
        if other is None:
            return False
        return self.id == other.id

    def addChild(self, item):
        if item not in self.children:
            item.parent = self
            self.children.append(item)
            return True
        return False

    def accumulateTimesOfChildren(self):
        self.hoursEstimate = sum(c.hoursEstimate for c in self.children)
        self.hoursSpent = sum(c.hoursSpent for c in self.children)
        return self.hoursEstimate, self.hoursSpent

    def accumulateTimes(self):
        if self.type == "issue":
            return self.hoursEstimate, self.hoursSpent
        if self.type == "epic":
            for c in self.children:
                e, s = c.accumulateTimes()
                self.hoursEstimate += e
                self.hoursSpent += s
        return self.hoursEstimate, self.hoursSpent