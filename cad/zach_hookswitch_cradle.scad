difference() {
    union() {
        sphere(r=8);
        cylinder(h=7,r=8);
        rotate([90,0,0])
            cylinder(h=13.5,r=8);
        translate([0,-13.5/2,3])
            cube([16,13.5,7],center = true);
        
        translate([0,12,4.3])
            resize([57,51,0])
                import("/home/zach/Downloads/Phone handset hook cradle - 3928257/files/Phone_Handset_Cradle_3.stl");
    }
    translate ([0,-1,0])
        union(){
            translate([0,0,6.2/2+8-6.2+1])
                rotate([0,0,90])
                    cube([13.2,6+0.1,6.3+2],center = true);
            translate([0,0,8-6.2-3])
                rotate([0,0,90])
                    cube([12.9,4.5,20],center = true);
        }
}