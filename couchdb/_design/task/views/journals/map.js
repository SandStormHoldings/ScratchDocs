function(doc) {
  if (doc.journal && doc.journal.length)
  	emit(doc._id, doc);
}
