trait laixin{
    type assoc;
    const C:Self::assoc;
    fn f(&self)->Self::assoc;
}
trait leixin{
    type assoc;
}
struct A;
struct B;