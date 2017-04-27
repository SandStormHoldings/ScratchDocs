function (doc) {
    emit(doc.path.slice(0,-1).join('/'),doc._id)
}
