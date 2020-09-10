def brancher(  # noqa: E302
    self, revs=None, all_branches=False, all_tags=False, all_commits=False
):
    """Generator that iterates over specified revisions.

    Args:
        revs (list): a list of revisions to iterate over.
        all_branches (bool): iterate over all available branches.
        all_commits (bool): iterate over all commits.
        all_tags (bool): iterate over all available tags.

    Yields:
        str: the display name for the currently selected tree, it could be:
            - a git revision identifier
            - empty string it there is no branches to iterate over
            - "workspace" if there are uncommitted changes in the SCM repo
    """
    saved_tree = self.tree

    try:
        for name, tree in self.scm.brancher(
            self.root_dir,
            revs=revs,
            all_branches=all_branches,
            all_tags=all_tags,
            all_commits=all_commits,
        ):
            self.tree = tree
            # ignore revs that don't contain repo root
            # (i.e. revs from before a subdir=True repo was init'ed)
            if self.tree.exists(self.root_dir) or name == "workspace":
                yield name
    finally:
        self.tree = saved_tree
