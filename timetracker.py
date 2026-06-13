import requests
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from Epic import Epic
from Issue import Issue

load_dotenv()

GITLAB_URL = "https://gitlab.com"

csv_rows = []
users = []
labels = []
_users_set = set()
_labels_set = set()

PAGE_SIZE = 100


def run_graphql_query(query, variables=None, token=None):
    api_token = token if token is not None else os.getenv("TOKEN")
    headers = {"Authorization": f"Bearer {api_token}"}
    response = requests.post(
        f"{GITLAB_URL}/api/graphql",
        headers=headers,
        json={"query": query, "variables": variables or {}}
    )
    response.raise_for_status()
    data = response.json()
    if 'errors' in data:
        raise Exception(data['errors'])
    return data['data']


def get_epic_with_items(group_path, epic_iid, token=None):
    query = """
    query EpicTree($groupPath: ID!, $epicIid: ID!, $first: Int) {
      group(fullPath: $groupPath) {
        epic(iid: $epicIid) {
          iid
          title
          children(first: $first) { nodes { iid } }
          issues(first: $first) {
            nodes {
              iid title createdAt timeEstimate totalTimeSpent state
              labels { nodes { title } }
              timelogs {
                nodes { timeSpent spentAt user { username name } }
              }
            }
          }
        }
      }
    }
    """
    variables = {"groupPath": group_path, "epicIid": epic_iid, "first": PAGE_SIZE}
    return run_graphql_query(query, variables, token)['group']['epic']


def _progress_noop(phase, pct, msg=None):
    pass


def _fetch_single_structure(group_path, epic_iid, token=None):
    """Fetch one epic's metadata (IID, title, child IIDs)."""
    query = """
    query EpicIIDs($groupPath: ID!, $epicIid: ID!, $first: Int) {
      group(fullPath: $groupPath) {
        epic(iid: $epicIid) {
          iid
          title
          children(first: $first) { nodes { iid } }
        }
      }
    }
    """
    variables = {"groupPath": group_path, "epicIid": epic_iid, "first": PAGE_SIZE}
    return run_graphql_query(query, variables, token)['group']['epic']


def _fetch_epic_structure_parallel(group_path, root_iid, token):
    """BFS-based parallel tree discovery. Returns nested (iid, title, children) tree."""
    root_data = _fetch_single_structure(group_path, root_iid, token)

    # Each node is [iid, title, unresolved_child_iids_list]
    # After children are fetched, unresolved list is replaced with child nodes
    root_node = [root_data['iid'], root_data['title'],
                 [c['iid'] for c in root_data['children']['nodes']]]
    current_level = [root_node]

    while current_level:
        children_to_fetch = []
        for node in current_level:
            children_to_fetch.extend(node[2])

        if not children_to_fetch:
            break

        child_data_map = {}
        with ThreadPoolExecutor(max_workers=min(max(len(children_to_fetch), 1), 10)) as pool:
            fut_map = {
                pool.submit(_fetch_single_structure, group_path, c_iid, token): c_iid
                for c_iid in children_to_fetch
            }
            for future in as_completed(fut_map):
                c_iid = fut_map[future]
                d = future.result()
                child_data_map[c_iid] = [d['iid'], d['title'],
                                         [c['iid'] for c in d['children']['nodes']]]

        next_level = []
        for node in current_level:
            resolved = []
            for c_iid in node[2]:
                child_node = child_data_map.get(c_iid)
                if child_node:
                    resolved.append(child_node)
                    next_level.append(child_node)
            node[2] = resolved

        current_level = next_level

    return tuple(root_node)


def accumulateEpicTree(group_path=None, epic_iid=None, parent_iid=None, token=None, progress_callback=None):
    if progress_callback is None:
        progress_callback = _progress_noop
    if group_path is None:
        group_path = os.getenv("GROUP_FULL_PATH")
    if epic_iid is None:
        epic_iid = os.getenv("EPIC_ROOT_ID")
    if token is None:
        token = os.getenv("TOKEN")

    if not group_path:
        raise ValueError("GROUP_FULL_PATH is required")
    if not epic_iid:
        raise ValueError("EPIC_ROOT_ID is required")
    if not token:
        raise ValueError("TOKEN is required")

    _users_set.clear()
    _labels_set.clear()

    # Phase 1: discover all epic IIDs and tree structure (lightweight queries)
    progress_callback("discover", 2, "Discovering epic tree structure...")
    print("Discovering epic tree structure...")
    tree_structure = _fetch_epic_structure_parallel(group_path, epic_iid, token)

    # Collect all IIDs flat for parallel fetching
    def _collect_iids(node):
        iid, title, children = node
        yield iid
        for c in children:
            yield from _collect_iids(c)

    all_iids = list(_collect_iids(tree_structure))
    progress_callback("discover", 5, f"Found {len(all_iids)} epics")
    print(f"Found {len(all_iids)} epics, fetching details in parallel...")

    # Phase 2: fetch all epics with issues in parallel
    epic_objects = {}
    total = len(all_iids)
    completed = 0

    phase2_start_pct = 5
    phase2_end_pct = 95

    with ThreadPoolExecutor(max_workers=min(len(all_iids), 10)) as pool:
        fut_map = {
            pool.submit(get_epic_with_items, group_path, iid, token): iid
            for iid in all_iids
        }
        for future in as_completed(fut_map):
            iid = fut_map[future]
            try:
                data = future.result()
                completed += 1
                pct = phase2_start_pct + (completed / total) * (phase2_end_pct - phase2_start_pct)
                progress_callback("fetch", int(pct), f"Fetching epics ({completed}/{total})")
                print(f"  Fetched: {data['title']} (IID: {iid})")
                epic_obj = Epic(data['title'], data['iid'])
                epic_objects[iid] = epic_obj

                for issue in data['issues']['nodes']:
                    i = Issue(issue['title'], issue['iid'])
                    i.hoursEstimate = (issue['timeEstimate'] or 0) / 3600.0
                    i.hoursSpent = (issue['totalTimeSpent'] or 0) / 3600.0
                    i.createdAt = issue.get('createdAt')
                    i.state = issue.get('state')

                    for log in issue['timelogs']['nodes']:
                        user_name = log['user']['name'] or log['user']['username']
                        i.addTimeSpentByUser(log['timeSpent'] / 3600.0, user_name, log['spentAt'])
                        _users_set.add(user_name)

                    for lab in issue['labels']['nodes']:
                        i.addLabel(lab['title'])
                        _labels_set.add(lab['title'])

                    epic_obj.addChild(i)

            except Exception as e:
                completed += 1
                pct = phase2_start_pct + (completed / total) * (phase2_end_pct - phase2_start_pct)
                progress_callback("fetch", int(pct), f"Fetching epics ({completed}/{total})")
                print(f"Error fetching epic {iid}: {e}")

    globals()['users'] = sorted(_users_set)
    globals()['labels'] = sorted(_labels_set)

    # Phase 3: wire up parent/child references using the tree structure (no API calls)
    progress_callback("wiring", 97, "Wiring tree structure...")
    print("Wiring tree structure...")

    def _wire_tree(node):
        iid, title, children = node
        epic_obj = epic_objects.get(iid)
        if epic_obj is None:
            epic_obj = Epic(title, iid)
            epic_objects[iid] = epic_obj
        for child_node in children:
            child_epic = _wire_tree(child_node)
            epic_obj.addChild(child_epic)
        return epic_obj

    root = _wire_tree(tree_structure)
    progress_callback("done", 100, "Building data rows...")
    return root


def build_rows_from_epic(e):
    parentId = None if (e.parent is None) else e.parent.id
    row = {
        "Typ": e.type, "Titel": e.title, "IID": e.id,
        "Parent IID": parentId,
        "Zeitaufwand (h)": round(e.hoursSpent, 2),
        "gesch. Zeitaufwand (h)": round(e.hoursEstimate, 2)
    }
    if e.type == "issue":
        row.update(e.getUserPercentagesByTime())
        row.update([(l, e.hasLabel(l)) for l in labels])
        row["createdAt"] = getattr(e, 'createdAt', None)
    else:
        row["createdAt"] = None
    csv_rows.append(row)
    for child in e.children:
        build_rows_from_epic(child)


if __name__ == "__main__":
    GROUP_FULL_PATH = os.getenv("GROUP_FULL_PATH")
    EPIC_IID = os.getenv("EPIC_ROOT_ID")
    TOKEN = os.getenv("TOKEN")

    if not GROUP_FULL_PATH or not EPIC_IID or not TOKEN:
        print("Error: Missing required environment variables!")
        exit(1)

    print(f"Fetching data for Epic {EPIC_IID} in {GROUP_FULL_PATH}...")
    epic = accumulateEpicTree(GROUP_FULL_PATH, EPIC_IID, token=TOKEN)
    epic.accumulateTimes()

    build_rows_from_epic(epic)
    print(f"Rows: {len(csv_rows)}")
    print("Data loaded successfully!")

