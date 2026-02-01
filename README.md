# VersiRef Search

[VersiRef](https://github.com/fiapps/versiref) is a Python package for sophisticated parsing, manipulation, and printing of references to the Bible.

To search a file in a text-based format for references to a Bible passage, you could use `versiref.RefParser` to parse all citations of Scripture and check these to see if they include a verse or verses of interest.
For repeatedly searching the same text, this is slow.
This package lets you build an indexed version of a Markdown text in the form of an SQLite database and search such a database.
