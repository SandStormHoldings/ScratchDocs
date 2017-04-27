#kindly borrowed from http://www.acooke.org/cute/ASCIIDispl0.html
class Tree(object):
    def __init__(self, name, *children):
        self.name = name
        self.children = children

    def __str__(self):
        return '\n'.join(self.tree_lines())

    def __unicode__(self):
        return u'\n'.join(self.tree_lines())

    def tree_lines(self):
        yield self.name
        last = self.children[-1] if self.children else None
        for child in self.children:
            prefix = '`-' if child is last else '+-'
            for line in child.tree_lines():
                yield prefix + line
                prefix = '  ' if child is last else '  '

      # an alternative without generators
    def tree_lines_2(self):
        lines = []
        lines.append(self.name)
        last = self.children[-1] if self.children else None
        for child in self.children:
            prefix = '`-' if child is last else '+-'
            for line in child.tree_lines():
                lines.append(prefix + line)
                prefix = '  ' if child is last else '| '
        return lines
