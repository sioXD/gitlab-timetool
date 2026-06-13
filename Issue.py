from Workitem import Workitem
import datetime as dt


class Issue(Workitem):
    type = "issue"

    def __init__(self, title, id):
        super().__init__(title, id)
        self.userTimeMap = {}
        self.labels = []

    def addTimeSpentByUser(self, time, user, date):
        if user in self.userTimeMap:
            self.userTimeMap[user].append({
                'Zeit(Std)': time,
                'Datum': date
            })
        else:
            self.userTimeMap[user] = [{
                'Zeit(Std)': time,
                'Datum': date
            }]

    def addLabel(self, label):
        if label not in self.labels:
            self.labels.append(label)

    def hasLabel(self, label):
        return label in self.labels

    def getLabels(self):
        return self.labels

    def getUserTimesDated(self, user):
        return self.userTimeMap.get(user, [])

    def getUserTotalTime(self, user):
        entries = self.userTimeMap.get(user, [])
        return sum(e['Zeit(Std)'] for e in entries)

    def getUserPercentagesByTime(self):
        if not self.userTimeMap:
            return {}
        userTimes = {}
        total = 0
        for user, entries in self.userTimeMap.items():
            t = sum(e['Zeit(Std)'] for e in entries)
            userTimes[user] = t
            total += t
        if total < 0.001:
            return {}
        self.hoursSpent = total
        for user in userTimes:
            userTimes[user] /= total
        return userTimes
        
    if __name__ == "__main__":
        from Issue import Issue

        isu = Issue("Hello",1)
        isu.addLabel("Pronto")
        isu.addLabel("LOL")
        isu.addTimeSpentByUser(0.5,"Nivek",dt.datetime(2025,10,16))
        print(isu.userTimeMap)
        isu.addTimeSpentByUser(2.5,"Nivek",dt.datetime(2025,10,26))
        print(isu.userTimeMap)
        isu.addTimeSpentByUser(0.5,"Bürek",dt.datetime(2025,11,16))
        print(isu.userTimeMap)
        print(isu.getUserPercentagesByTime())